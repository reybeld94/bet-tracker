from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.ingestion.espn_parser import parse_scoreboard
from app.picks.enqueue import _enqueue_for_game
from app.picks.worker import _is_in_pregame_window


class EspnParserTests(unittest.TestCase):
    def test_parse_scoreboard_skips_events_without_valid_start_time(self) -> None:
        payload = {
            "events": [
                {
                    "id": "ok-event",
                    "date": "2026-02-10T03:00Z",
                    "competitions": [
                        {
                            "id": "ok-comp",
                            "status": {"type": {"state": "pre"}},
                            "competitors": [
                                {"homeAway": "home", "team": {"displayName": "A"}, "score": "0"},
                                {"homeAway": "away", "team": {"displayName": "B"}, "score": "0"},
                            ],
                        }
                    ],
                },
                {
                    "id": "bad-event",
                    "date": "not-a-date",
                    "competitions": [
                        {
                            "id": "bad-comp",
                            "status": {"type": {"state": "pre"}},
                            "competitors": [
                                {"homeAway": "home", "team": {"displayName": "C"}, "score": "0"},
                                {"homeAway": "away", "team": {"displayName": "D"}, "score": "0"},
                            ],
                        }
                    ],
                },
            ]
        }

        games = parse_scoreboard(payload, "NBA")

        self.assertEqual(1, len(games))
        self.assertEqual("ok-comp", games[0].provider_event_id)


class PregameWindowTests(unittest.TestCase):
    def test_is_in_pregame_window_true_within_two_hours_before_start(self) -> None:
        now = datetime(2026, 2, 10, 1, 30, tzinfo=timezone.utc)
        start = datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc)

        self.assertTrue(_is_in_pregame_window(start, now_utc=now))

    def test_is_in_pregame_window_false_after_start(self) -> None:
        now = datetime(2026, 2, 10, 3, 1, tzinfo=timezone.utc)
        start = datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc)

        self.assertFalse(_is_in_pregame_window(start, now_utc=now))


class EnqueueForGameTests(unittest.TestCase):
    def test_enqueue_for_game_does_not_enqueue_when_outside_window(self) -> None:
        class _StubGame:
            id = 10
            start_time_utc = datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc)
            status = "scheduled"

        class _StubQuery:
            def filter(self, *_, **__):
                return self

            def one_or_none(self):
                return None

        class _StubDB:
            def __init__(self):
                self.added = []

            def query(self, *_):
                return _StubQuery()

            def add(self, obj):
                self.added.append(obj)

        db = _StubDB()
        now = datetime(2026, 2, 9, 23, 59, tzinfo=timezone.utc)

        created = _enqueue_for_game(db, _StubGame(), now=now, pregame_window_hours=2)

        self.assertFalse(created)
        self.assertEqual([], db.added)


if __name__ == "__main__":
    unittest.main()
