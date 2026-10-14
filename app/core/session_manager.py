"""Điều phối luồng xe vào/ra — tương đương luồng TblVanHanh -> TblDoanhThu của
phần mềm cũ, nhưng nguồn dữ liệu đầu vào là AlprPipeline (AI) thay vì SDK
SimpleLPR + thẻ từ như bản cũ (xem mục 4 "Đối chiếu: giữ gì, thêm gì" trong
QUY_TRINH_LAM_LAI_PHAN_MEM.md).
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy.orm import Session

from app.alpr.pipeline import PlateReading
from app.config import config
from app.core.fee import calculate_fee_db
from app.db.models import ShiftSummary, Transaction, VehicleSession
from app.occupancy.flow_counter import FlowCounter

logger = logging.getLogger("session_manager")


class VehicleSessionManager:
    def __init__(self, db: Session, flow_counter: FlowCounter, fee_schedule: dict):
        self.db = db
        self.flow_counter = flow_counter
        self.fee_schedule = fee_schedule

    def handle_entry(self, reading: PlateReading, vehicle_type: str,
                      image_path: str | None = None) -> VehicleSession:
        session = VehicleSession(
            vehicle_type_code=vehicle_type,
            time_in=dt.datetime.utcnow(),
            plate_in=reading.text or None,
            plate_in_confidence=reading.confidence,
            image_in_path=image_path,
            status="open",
        )
        self.db.add(session)
        self.db.commit()
        self.flow_counter.record_entry(vehicle_type)
        logger.info("Xe vào: loai=%s bien_so=%r conf=%.2f", vehicle_type, reading.text, reading.confidence)
        return session

    def handle_exit(self, session: VehicleSession, reading: PlateReading,
                     image_path: str | None = None,
                     work_shift_id: int | None = None,
                     amount_override: int | None = None) -> Transaction:
        time_out = dt.datetime.utcnow()
        session.time_out = time_out
        session.plate_out = reading.text or None
        session.plate_out_confidence = reading.confidence
        session.image_out_path = image_path
        session.status = "closed"

        if amount_override is not None:  # vé tháng: không thu phí lượt
            amount = amount_override
        else:
            amount = calculate_fee_db(self.db, session.vehicle_type_code, session.time_in, time_out,
                                      self.fee_schedule, config.get("timezone_offset_hours", 7))
        transaction = Transaction(
            session_id=session.id,
            time_in=session.time_in,
            time_out=time_out,
            amount=amount,
            plate_in=session.plate_in,
            plate_out=session.plate_out,
            work_shift_id=work_shift_id,
        )
        self.db.add(transaction)
        self.db.commit()
        self.flow_counter.record_exit(session.vehicle_type_code)

        if session.plate_in and reading.text and session.plate_in != reading.text:
            logger.warning(
                "Biển số vào/ra KHÔNG khớp cho session %s: vao=%r ra=%r — cần bảo vệ kiểm tra thủ công",
                session.id, session.plate_in, reading.text,
            )
        logger.info("Xe ra: loai=%s bien_so=%r tien=%d", session.vehicle_type_code, reading.text, amount)
        return transaction

    def save_shift_summary(self, shift_id: int, start_time: dt.datetime) -> ShiftSummary:
        snapshot = self.flow_counter.snapshot()
        summary = ShiftSummary(
            shift_id=shift_id,
            start_time=start_time,
            end_time=dt.datetime.utcnow(),
            vehicles_in=sum(v["in"] for v in snapshot.values()),
            vehicles_out=sum(v["out"] for v in snapshot.values()),
            counts_by_type_json=json.dumps(snapshot, ensure_ascii=False),
        )
        self.db.add(summary)
        self.db.commit()
        return summary
