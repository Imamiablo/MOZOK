# 48 - World Event Bus V2

Moved world events from metadata-backed storage to a dedicated SQL-backed event bus.

## Added

- `WorldEventRecord` SQL model in `mozok/db/models.py`.
- Event TTL/expiry support.
- Consumed-by-agent history.
- Acknowledged-by-agent history.
- Durable active/inactive event history.

## Routes

- Existing:
  - `POST /world-events`
  - `POST /world-events/search`
  - `POST /world-events/to-perception`
- New:
  - `POST /world-events/consume`
  - `POST /world-events/ack`
  - `POST /world-events/expire`

## Compatibility

The public event shape remains adapter-neutral. Game/app/tool integrations can keep publishing events through the same create/search/to-perception flow while gaining consume/ack/TTL handling.
