"""Driver phần cứng barie thật — gửi tín hiệu đóng/mở qua cổng COM (hoặc TCP
cho 1 vài cổng), đúng theo yêu cầu: giữ nguyên cách gửi tín hiệu của phần mềm
cũ, chỉ đổi người ra quyết định "khi nào đóng" từ (thẻ từ + không cảm biến)
sang AI (`BarrierSafetyZone`, xem controller.py).

Cấu hình `openCommand`/`closeCommand` dưới đây **copy nguyên văn** từ
`giuxe/giuxe1/Debug_MSSQL/Debug/Debug_MSSQL/Debug/app.config.xml`
(khối `<Barriers>`), để tham khảo đúng giao thức phần cứng thật:

    <Barrier id="1" port="COM19" openCommand="RYA1000000005" closeCommand="3T000010" />
    <Barrier id="2" port="TCP:192.168.1.5:2000" openCommand="&lt;02&gt;RYA&lt;02&gt;" closeCommand="3T000020" />
    <Barrier id="3" port="COM23" openCommand="3T000031" closeCommand="3T000030" />
    ... (id 4-10 cùng dạng "3T0000{id:02d}{1|0}" trên COM23)

⚠️ 2 điểm KHÔNG chắc chắn, cần bạn/nhà cung cấp relay board xác nhận trước
khi dùng cho barie thật — tôi không có cách kiểm chứng những điều này mà
không có phần cứng thật:
1. Ký hiệu `<02>` trong file cấu hình gốc được hiểu ở đây là 1 byte điều
   khiển (0x02, STX) viết dưới dạng hex trong text — xem `_encode_command()`.
   Đây là cách diễn giải hợp lý nhất nhưng chưa được xác minh bằng thiết bị
   thật.
2. Barrier id=1 có `openCommand` khác hẳn format "3T0000.." của các id khác
   (dùng "RYA1000000005") — có thể do dùng board/kênh khác, giữ nguyên đúng
   như file gốc, không tự sửa cho "nhất quán".

Mặc định hệ thống dùng `LoggingHardware` (chỉ log, không gửi gì ra phần cứng)
— chỉ đổi sang `SerialBarrierHardware` khi `barrier_hardware.type: serial`
trong config, để tránh gửi nhầm lệnh ra relay thật khi còn đang test code.
"""
from __future__ import annotations

import logging
import re
import socket
import threading

import serial

logger = logging.getLogger("barrier.hardware")

_HEX_TAG = re.compile(r"<([0-9A-Fa-f]{2})>")


def _encode_command(command: str) -> bytes:
    """"<02>RYA<02>" -> b'\\x02RYA\\x02'; "3T000010" -> b'3T000010' (ASCII thường)."""
    result = bytearray()
    pos = 0
    for match in _HEX_TAG.finditer(command):
        result += command[pos:match.start()].encode("ascii")
        result.append(int(match.group(1), 16))
        pos = match.end()
    result += command[pos:].encode("ascii")
    return bytes(result)


class _TcpPort:
    """Interface tối thiểu giống pyserial.Serial, cho các barie dùng port "TCP:host:port"."""

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self._addr = (host, port)
        self._timeout = timeout
        self._sock: socket.socket | None = None

    def write(self, data: bytes) -> None:
        if self._sock is None:
            self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        self._sock.sendall(data)


class SerialBarrierHardware:
    """Implement `BarrierHardware` protocol (send_open/send_close), xem
    app/barrier/controller.py. `barriers` là dict id -> {port, open_command, close_command},
    nên lấy nguyên từ config/config.yaml (mục `barrier_hardware.barriers`)."""

    def __init__(self, barriers: dict[str, dict], baudrate: int = 9600):
        self.barriers = barriers
        self.baudrate = baudrate
        self._lock = threading.Lock()
        self._ports: dict[str, serial.Serial | _TcpPort] = {}

    def _get_port(self, port_spec: str):
        if port_spec in self._ports:
            return self._ports[port_spec]
        if port_spec.startswith("TCP:"):
            _, host, tcp_port = port_spec.split(":")
            conn = _TcpPort(host, int(tcp_port))
        else:
            conn = serial.Serial(port_spec, self.baudrate, timeout=1)
        self._ports[port_spec] = conn
        return conn

    def _send(self, barrier_id: str, command_key: str) -> None:
        spec = self.barriers.get(barrier_id)
        if not spec:
            logger.error("Không có cấu hình cho barrier_id=%s", barrier_id)
            return
        command = spec[command_key]
        with self._lock:
            try:
                port = self._get_port(spec["port"])
                port.write(_encode_command(command))
                logger.info("Barie %s: gửi %s=%r qua %s", barrier_id, command_key, command, spec["port"])
            except Exception:
                logger.exception("Lỗi gửi lệnh tới barie %s qua %s", barrier_id, spec["port"])

    def send_open(self, barrier_id: str) -> None:
        self._send(barrier_id, "open_command")

    def send_close(self, barrier_id: str) -> None:
        self._send(barrier_id, "close_command")
