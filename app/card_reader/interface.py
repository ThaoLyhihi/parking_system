"""Interface đầu đọc thẻ — đã đổi từ cổng COM (phần mềm cũ, `coms.config`:
`COM7`) sang **đầu đọc thẻ cổng USB** theo yêu cầu mới.

Phần lớn đầu đọc thẻ RFID/thẻ từ giá rẻ dùng cổng USB đều giả lập bàn phím
(USB HID keyboard wedge): khi quẹt/chạm thẻ, đầu đọc "gõ" số thẻ rồi gõ Enter,
giống hệt người gõ phím — khớp với cấu hình `CardReader format="MIXED"` của
phần mềm cũ (đọc số thẻ dạng chuỗi ký tự). Đây là giả định mặc định hợp lý
nhất khi chưa biết chính xác model đầu đọc — xem `usb_hid_reader.py`.

Nếu đầu đọc thật của bạn dùng giao thức HID riêng (không phải keyboard wedge),
viết thêm 1 class implement `CardReader` dùng thư viện `hidapi` thay vì
`evdev`, giữ nguyên interface này.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class CardReader(ABC):
    @abstractmethod
    def start(self, on_card: Callable[[str], None]) -> None:
        """Bắt đầu lắng nghe thẻ trong background; gọi on_card(card_number) mỗi khi quẹt thẻ."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError
