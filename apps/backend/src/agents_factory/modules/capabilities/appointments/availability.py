from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from agents_factory.modules.capabilities.appointments.models import (
    AppointmentsConfig,
    BusyInterval,
    Service,
    Slot,
)


def local_instants(day: date, wall: time, zone: ZoneInfo) -> tuple[datetime, ...]:
    """Skip DST gaps; represent both explicit UTC instants in an autumn fold."""
    naive = datetime.combine(day, wall)
    values = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            values.add(utc)
    return tuple(sorted(values))


def candidate_slot(
    config: AppointmentsConfig, service: Service, start: datetime, *, now: datetime
) -> Slot | None:
    if start.tzinfo is None or now.tzinfo is None:
        return None
    instant = start.astimezone(UTC)
    zone = ZoneInfo(config.timezone)
    local = instant.astimezone(zone)
    if (
        local.date() in config.closed_dates
        or instant < now.astimezone(UTC) + timedelta(minutes=config.lead_minutes)
        or local.date()
        > now.astimezone(zone).date() + timedelta(days=config.booking_horizon_days)
        or local.second
        or local.microsecond
    ):
        return None
    end = instant + timedelta(minutes=service.duration_minutes)
    before = instant - timedelta(minutes=service.buffer_before_minutes)
    after = end + timedelta(minutes=service.buffer_after_minutes)
    for hours in config.working_hours:
        if hours.weekday != local.weekday():
            continue
        minute_offset = (local.hour * 60 + local.minute) - (
            hours.start.hour * 60 + hours.start.minute
        )
        if minute_offset < 0 or minute_offset % config.slot_step_minutes:
            continue
        openings = local_instants(local.date(), hours.start, zone)
        closings = local_instants(local.date(), hours.end, zone)
        if openings and closings and min(openings) <= before and after <= max(closings):
            return Slot(start=instant, end=end, busy_start=before, busy_end=after)
    return None


def is_free(slot: Slot, occupied: tuple[BusyInterval, ...]) -> bool:
    return all(
        slot.busy_end <= item.start or slot.busy_start >= item.end for item in occupied
    )


def available_slots(
    config: AppointmentsConfig,
    service_id: str,
    day: date,
    *,
    now: datetime,
    occupied: tuple[BusyInterval, ...],
) -> tuple[Slot, ...]:
    service, zone = config.service(service_id), ZoneInfo(config.timezone)
    slots: dict[datetime, Slot] = {}
    for hours in config.working_hours:
        if hours.weekday != day.weekday():
            continue
        wall = datetime.combine(day, hours.start)
        end_wall = datetime.combine(day, hours.end)
        while wall < end_wall:
            for start in local_instants(day, wall.time(), zone):
                slot = candidate_slot(config, service, start, now=now)
                if slot is not None and is_free(slot, occupied):
                    slots[slot.start] = slot
            wall += timedelta(minutes=config.slot_step_minutes)
    return tuple(slots[start] for start in sorted(slots))
