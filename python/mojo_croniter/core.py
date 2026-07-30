from __future__ import annotations

import calendar
import datetime as _datetime
import math
import re
import time
from collections.abc import Generator, Iterator
from typing import Any

import numpy as np

from ._lib import lib

MINUTE_FIELD = 0
HOUR_FIELD = 1
DAY_FIELD = 2
MONTH_FIELD = 3
DOW_FIELD = 4
SECOND_FIELD = 5
YEAR_FIELD = 6

UTC_DT = _datetime.timezone.utc
OVERFLOW32B_MODE = False
NO_MATCH = -9223372036854775807
INVALID_ARGUMENT = -9223372036854775806
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6), (0, 59), (1970, 2099))
_OFFSETS = (0, 60, 84, 116, 129, 136, 196)
_LENGTHS = (60, 24, 32, 13, 7, 60, 130)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAYS = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}
_ALIASES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


class CroniterError(ValueError):
    pass


class CroniterBadTypeRangeError(TypeError):
    pass


class CroniterBadCronError(CroniterError):
    pass


class CroniterUnsupportedSyntaxError(CroniterBadCronError):
    pass


class CroniterBadDateError(CroniterError):
    pass


class CroniterNotAlphaError(CroniterBadCronError):
    pass


def datetime_to_timestamp(value: _datetime.datetime) -> float:
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None) - value.utcoffset()
    return (value - _datetime.datetime(1970, 1, 1)).total_seconds()


def _replace_names(text: str, field: int) -> str:
    names = _MONTHS if field == MONTH_FIELD else _WEEKDAYS if field == DOW_FIELD else {}

    def replace(match: re.Match[str]) -> str:
        key = match.group(0)
        if key not in names:
            raise CroniterNotAlphaError(f"unknown name {key!r}")
        return str(names[key])

    if re.search(r"[a-z]", text):
        return re.sub(r"[a-z]{3}", replace, text)
    return text


def _range_values(low: int, high: int, step: int, field: int) -> list[int]:
    minimum, maximum = _RANGES[field]
    input_maximum = 7 if field == DOW_FIELD else maximum
    if low < minimum or low > input_maximum or high < minimum or high > input_maximum:
        raise CroniterBadCronError("value out of range")
    if low == high:
        values = list(range(low, input_maximum + 1)) + list(range(minimum, low))
    elif low < high:
        values = list(range(low, high + 1))
    else:
        values = list(range(low, input_maximum + 1)) + list(range(minimum, high + 1))
    values = values[::step]
    if field == DOW_FIELD:
        values = [0 if value == 7 else value for value in values]
    return values


def _parse_field(
    expression: str,
    field: int,
    nth: dict[int, set[int | str]],
    special: dict[str, int],
    from_dt: _datetime.datetime | None,
) -> list[int | str]:
    text = _replace_names(expression.lower(), field)
    if text == "?" and field in (DAY_FIELD, DOW_FIELD):
        text = "*"
    if text == "*":
        return ["*"]
    if any(token.startswith(("h", "r")) for token in text.split(",")):
        raise CroniterUnsupportedSyntaxError("hashed and random cron fields are not supported")

    parts = text.split(",")
    if any(not part for part in parts):
        raise CroniterBadCronError("empty list item")
    if field == DAY_FIELD and any("w" in part for part in parts):
        if len(parts) != 1 or not re.fullmatch(r"\d+w", parts[0]):
            raise CroniterBadCronError("'W' requires one day-of-month value")
        nearest = int(parts[0][:-1])
        if not 1 <= nearest <= 31:
            raise CroniterBadCronError("nearest weekday is out of range")
        special["nearest"] = nearest
        return [nearest]

    values: list[int | str] = []
    for part in parts:
        if field == DAY_FIELD and part == "l":
            special["dom_last"] = 1
            values.append("l")
            continue
        if field == DOW_FIELD:
            match = re.fullmatch(r"l([0-7])", part)
            if match:
                weekday = int(match.group(1)) % 7
                nth.setdefault(weekday, set()).add("l")
                values.append(weekday)
                continue
            match = re.fullmatch(r"([0-7])#([1-5])", part)
            if match:
                weekday, occurrence = int(match.group(1)) % 7, int(match.group(2))
                nth.setdefault(weekday, set()).add(occurrence)
                values.append(weekday)
                continue
        if re.search(r"[a-z]", part):
            raise CroniterNotAlphaError(f"invalid alpha value in {expression!r}")

        match = re.fullmatch(r"([^-/]+)-([^/]+)(?:/(\d+))?", part)
        if match:
            step = int(match.group(3) or 1)
            if step <= 0:
                raise CroniterBadCronError("step must be positive")
            try:
                low, high = int(match.group(1)), int(match.group(2))
            except ValueError as exc:
                raise CroniterBadCronError("invalid range") from exc
            values.extend(_range_values(low, high, step, field))
            continue

        match = re.fullmatch(r"([^/]+)/(\d+)", part)
        if match:
            step = int(match.group(2))
            if step <= 0:
                raise CroniterBadCronError("step must be positive")
            first = match.group(1)
            minimum, maximum = _RANGES[field]
            if first == "*":
                low = minimum
                if from_dt is not None and field < SECOND_FIELD:
                    current = (
                        from_dt.minute, from_dt.hour, from_dt.day,
                        from_dt.month, (from_dt.weekday() + 1) % 7,
                    )[field]
                    low += (current - minimum) % step
            else:
                try:
                    low = int(first)
                except ValueError as exc:
                    raise CroniterBadCronError("invalid step range") from exc
            values.extend(_range_values(low, maximum, step, field))
            continue

        try:
            value = int(part)
        except ValueError as exc:
            raise CroniterBadCronError(f"invalid value {part!r}") from exc
        minimum, maximum = _RANGES[field]
        if field == DOW_FIELD and value == 7:
            value = 0
        elif value < minimum or value > maximum:
            raise CroniterBadCronError("value out of range")
        values.append(value)

    numeric = sorted({int(value) for value in values if value != "l"})
    result: list[int | str] = numeric
    if "l" in values:
        result.append("l")
    minimum, maximum = _RANGES[field]
    if (
        field not in (DAY_FIELD, DOW_FIELD)
        and "l" not in result
        and numeric == list(range(minimum, maximum + 1))
    ):
        return ["*"]
    return result


def _normalize_expression(expression: str, second_at_beginning: bool) -> list[str]:
    if not isinstance(expression, str):
        raise CroniterBadCronError("expression must be a string")
    expression = _ALIASES.get(expression.strip().lower(), expression)
    fields = expression.lower().split()
    if len(fields) not in (5, 6, 7):
        raise CroniterBadCronError("exactly 5, 6 or 7 columns are required")
    if second_at_beginning and len(fields) > 5:
        fields = fields[1:6] + [fields[0]] + fields[6:]
    return fields


def _parse(
    expression: str,
    second_at_beginning: bool = False,
    from_timestamp: float | None = None,
    strict: bool = False,
) -> tuple[list[list[int | str]], dict[int, set[int | str]], list[str], int]:
    fields = _normalize_expression(expression, second_at_beginning)
    from_dt = (
        _datetime.datetime.fromtimestamp(from_timestamp, UTC_DT)
        if from_timestamp is not None else None
    )
    nth: dict[int, set[int | str]] = {}
    special = {"dom_last": 0, "nearest": 0}
    expanded = [
        _parse_field(field, index, nth, special, from_dt)
        for index, field in enumerate(fields)
    ]
    full_dom = list(range(1, 32))
    full_dow = list(range(0, 7))
    # Upstream preserves an explicitly expanded full day field when the other
    # day field is restricted: syntactic restriction affects OR semantics.
    dom_wildcard_syntax = fields[DAY_FIELD] == "?" or fields[DAY_FIELD].startswith("*")
    dow_wildcard_syntax = fields[DOW_FIELD] == "?" or fields[DOW_FIELD].startswith("*")
    if expanded[DAY_FIELD] == full_dom and dow_wildcard_syntax:
        expanded[DAY_FIELD] = ["*"]
    if expanded[DOW_FIELD] == full_dow and dom_wildcard_syntax and not nth:
        expanded[DOW_FIELD] = ["*"]
    if nth and expanded[DAY_FIELD] != ["*"]:
        raise CroniterUnsupportedSyntaxError(
            "combining #/last-weekday with a restricted day-of-month is not supported"
        )
    if strict and expanded[DAY_FIELD] != ["*"] and expanded[DOW_FIELD] != ["*"]:
        raise CroniterBadCronError("strict mode forbids restricting both day fields")
    return expanded, nth, fields, special["nearest"]


def _compile_table(
    expanded: list[list[int | str]],
    nth: dict[int, set[int | str]],
    nearest: int,
) -> tuple[np.ndarray, np.ndarray]:
    table = np.zeros(326, dtype=np.uint8)
    for field in range(7):
        if field >= len(expanded):
            values: list[int | str] = [0] if field == SECOND_FIELD else ["*"]
        else:
            values = expanded[field]
        minimum, maximum = _RANGES[field]
        if values == ["*"]:
            low = 0 if field == YEAR_FIELD else minimum
            high = 129 if field == YEAR_FIELD else maximum
            table[_OFFSETS[field] + low:_OFFSETS[field] + high + 1] = 1
        else:
            for value in values:
                if value != "l":
                    normalized = int(value) - 1970 if field == YEAR_FIELD else int(value)
                    table[_OFFSETS[field] + normalized] = 1

    special = np.zeros(12, dtype=np.int64)
    special[0] = int(expanded[DAY_FIELD] == ["*"])
    special[1] = int(expanded[DOW_FIELD] == ["*"])
    special[2] = int("l" in expanded[DAY_FIELD])
    special[3] = nearest
    for weekday, occurrences in nth.items():
        mask = 0
        for occurrence in occurrences:
            mask |= 1 << (6 if occurrence == "l" else int(occurrence))
        special[4 + weekday] = mask
    special[11] = int(bool(nth))
    return table, special


def _buffer_address(array: np.ndarray, dtype: np.dtype, length: int, name: str) -> int:
    if (
        not isinstance(array, np.ndarray)
        or array.dtype != dtype
        or array.ndim != 1
        or array.size != length
        or not array.flags.c_contiguous
    ):
        raise RuntimeError(
            f"invalid {name} buffer: expected contiguous {dtype} array of length {length}"
        )
    address = int(array.ctypes.data)
    if address == 0:
        raise RuntimeError(f"invalid {name} buffer: null data pointer")
    return address


def _int64(value: int, name: str) -> int:
    value = int(value)
    if not _INT64_MIN <= value <= _INT64_MAX:
        raise CroniterBadDateError(f"{name} is outside the signed 64-bit range")
    return value


class croniter:
    RANGES = _RANGES
    ALPHACONV = ({}, {}, {"l": "l"}, _MONTHS.copy(), _WEEKDAYS.copy(), {}, {})
    LOWMAP = ({}, {}, {0: 1}, {0: 1}, {7: 0}, {}, {})
    LEN_MEANS_ALL = (60, 24, 31, 12, 7, 60, 130)

    def __init__(
        self,
        expr_format: str,
        start_time: _datetime.datetime | float | None = None,
        ret_type: type = float,
        day_or: bool = True,
        max_years_between_matches: int | None = None,
        is_prev: bool = False,
        hash_id: bytes | str | None = None,
        implement_cron_bug: bool = False,
        second_at_beginning: bool = False,
        expand_from_start_time: bool = False,
    ) -> None:
        if hash_id is not None and not isinstance(hash_id, (bytes, str)):
            raise TypeError("hash_id must be bytes or UTF-8 string")
        if implement_cron_bug:
            raise CroniterUnsupportedSyntaxError("implement_cron_bug is not supported")
        self._ret_type = ret_type
        self._day_or = bool(day_or)
        self._is_prev = bool(is_prev)
        self.second_at_beginning = bool(second_at_beginning)
        self._expand_from_start_time = bool(expand_from_start_time)
        self._max_years_btw_matches_explicitly_set = max_years_between_matches is not None
        self._max_years_between_matches = max(int(max_years_between_matches or 50), 1)
        self.tzinfo: _datetime.tzinfo | None = None
        self.start_time = 0.0
        self.dst_start_time = 0.0
        self.cur = 0.0
        self.set_current(time.time() if start_time is None else start_time, force=True)
        parsed = _parse(
            expr_format,
            second_at_beginning=second_at_beginning,
            from_timestamp=self.dst_start_time if expand_from_start_time else None,
        )
        self.expanded, self.nth_weekday_of_month, self.expressions, self.nearest_weekday = parsed
        self.fields = tuple(range(len(self.expanded)))
        self._table, self._special = _compile_table(
            self.expanded, self.nth_weekday_of_month, self.nearest_weekday
        )
        _buffer_address(self._table, np.dtype(np.uint8), 326, "membership")
        _buffer_address(self._special, np.dtype(np.int64), 12, "special-rules")

    def _ffi_buffers(self) -> tuple[np.ndarray, int, np.ndarray, int]:
        # Local references keep both NumPy allocations alive for the entire C call.
        table = self._table
        special = self._special
        return (
            table,
            _buffer_address(table, np.dtype(np.uint8), 326, "membership"),
            special,
            _buffer_address(special, np.dtype(np.int64), 12, "special-rules"),
        )

    def _ffi_one(self, is_prev: bool, wall: int) -> int:
        table, table_addr, special, special_addr = self._ffi_buffers()
        function = lib().mcron_prev if is_prev else lib().mcron_next
        result = function(
            table_addr,
            table.size,
            special_addr,
            special.size,
            _int64(wall, "start time"),
            int(self._day_or),
        )
        if result == INVALID_ARGUMENT:
            raise RuntimeError("Mojo kernel rejected the FFI buffer contract")
        return int(result)

    @classmethod
    def expand(
        cls,
        expr_format: str,
        hash_id: bytes | str | None = None,
        second_at_beginning: bool = False,
        from_timestamp: float | None = None,
        strict: bool = False,
        strict_year: int | list[int] | None = None,
    ) -> tuple[list[list[int | str]], dict[int, set[int | str]]]:
        if hash_id is not None and not isinstance(hash_id, (bytes, str)):
            raise TypeError("hash_id must be bytes or UTF-8 string")
        expanded, nth, _, _ = _parse(
            expr_format, second_at_beginning, from_timestamp, strict
        )
        if strict_year is not None and len(expanded) == 7:
            years = [strict_year] if isinstance(strict_year, int) else strict_year
            if expanded[YEAR_FIELD] == ["*"] or not set(years).issubset(expanded[YEAR_FIELD]):
                raise CroniterBadCronError("year does not satisfy strict_year")
        return expanded, nth

    @classmethod
    def is_valid(
        cls,
        expression: str,
        hash_id: bytes | str | None = None,
        encoding: str = "UTF-8",
        second_at_beginning: bool = False,
        strict: bool = False,
        strict_year: int | list[int] | None = None,
    ) -> bool:
        del encoding
        try:
            cls.expand(
                expression, hash_id, second_at_beginning, strict=strict,
                strict_year=strict_year,
            )
        except CroniterError:
            return False
        return True

    def set_current(
        self, start_time: _datetime.datetime | float | None, force: bool = True
    ) -> float:
        if force and start_time is not None:
            if isinstance(start_time, _datetime.datetime):
                self.tzinfo = start_time.tzinfo
                start_time = datetime_to_timestamp(start_time)
            self.start_time = float(start_time)
            self.dst_start_time = float(start_time)
            self.cur = float(start_time)
        return self.cur

    @staticmethod
    def datetime_to_timestamp(value: _datetime.datetime) -> float:
        return datetime_to_timestamp(value)

    _datetime_to_timestamp = datetime_to_timestamp

    def timestamp_to_datetime(
        self, timestamp: float, tzinfo: Any = ...
    ) -> _datetime.datetime:
        if tzinfo is ...:
            tzinfo = self.tzinfo
        result = _datetime.datetime.fromtimestamp(timestamp, UTC_DT).replace(tzinfo=None)
        if tzinfo is not None:
            result = result.replace(tzinfo=UTC_DT).astimezone(tzinfo)
        return result

    _timestamp_to_datetime = timestamp_to_datetime

    def _wall_start(self, is_prev: bool) -> int:
        if self.tzinfo is None:
            wall = math.floor(self.cur)
            return wall + 1 if is_prev and self.cur != wall else wall
        current = self.timestamp_to_datetime(self.cur)
        wall = calendar.timegm(current.replace(tzinfo=None).timetuple())
        return wall + 1 if is_prev and current.microsecond else wall

    def _resolve_wall(self, wall: int, is_prev: bool) -> tuple[float, _datetime.datetime]:
        naive = _datetime.datetime.fromtimestamp(wall, UTC_DT).replace(tzinfo=None)
        if self.tzinfo is None:
            return float(wall), naive
        candidates = [
            naive.replace(tzinfo=self.tzinfo, fold=fold)
            for fold in (0, 1)
        ]
        valid: list[tuple[float, _datetime.datetime]] = []
        for candidate in candidates:
            timestamp = candidate.timestamp()
            roundtrip = _datetime.datetime.fromtimestamp(timestamp, self.tzinfo)
            if roundtrip.replace(tzinfo=None) == naive:
                valid.append((timestamp, candidate))
        if not valid:
            adjusted = naive
            while True:
                adjusted += _datetime.timedelta(minutes=1)
                candidate = adjusted.replace(tzinfo=self.tzinfo, fold=0)
                timestamp = candidate.timestamp()
                roundtrip = _datetime.datetime.fromtimestamp(timestamp, self.tzinfo)
                if roundtrip.replace(tzinfo=None) == adjusted:
                    return timestamp, roundtrip
        directional = [
            item for item in valid
            if (item[0] < self.cur if is_prev else item[0] > self.cur)
        ]
        pool = directional or valid
        return (max(pool) if is_prev else min(pool))

    def _ambiguous_alternate(self, is_prev: bool) -> tuple[float, _datetime.datetime] | None:
        if self.tzinfo is None:
            return None
        current = self.timestamp_to_datetime(self.cur)
        if current.microsecond:
            return None
        naive = current.replace(tzinfo=None)
        wall = calendar.timegm(naive.timetuple())
        previous = self._ffi_one(True, wall + 1)
        if previous != wall:
            return None
        candidates = {
            candidate.timestamp(): candidate
            for candidate in (
                naive.replace(tzinfo=self.tzinfo, fold=0),
                naive.replace(tzinfo=self.tzinfo, fold=1),
            )
            if _datetime.datetime.fromtimestamp(
                candidate.timestamp(), self.tzinfo
            ).replace(tzinfo=None) == naive
        }
        directional = [
            (timestamp, candidate)
            for timestamp, candidate in candidates.items()
            if timestamp < self.cur if is_prev
        ] if is_prev else [
            (timestamp, candidate)
            for timestamp, candidate in candidates.items()
            if timestamp > self.cur
        ]
        if not directional:
            return None
        return max(directional) if is_prev else min(directional)

    def _get_next(
        self,
        ret_type: type | None = None,
        start_time: _datetime.datetime | float | None = None,
        is_prev: bool | None = None,
        update_current: bool | None = None,
    ):
        if start_time is not None:
            self.set_current(start_time, force=True)
        if is_prev is None:
            is_prev = self._is_prev
        self._is_prev = is_prev
        if update_current is None:
            update_current = True
        ret_type = ret_type or self._ret_type
        if not isinstance(ret_type, type) or not issubclass(ret_type, (float, _datetime.datetime)):
            raise TypeError("Invalid ret_type, only 'float' or 'datetime' is acceptable.")
        returns_datetime = issubclass(ret_type, _datetime.datetime)
        alternate = self._ambiguous_alternate(is_prev)
        if alternate is not None:
            timestamp, result = alternate
            if update_current:
                self.cur = timestamp
            return result if returns_datetime else timestamp
        wall = self._ffi_one(is_prev, self._wall_start(is_prev))
        if wall == NO_MATCH:
            raise CroniterBadDateError("failed to find a matching date")
        if self.tzinfo is None and not returns_datetime:
            timestamp = float(wall)
            if (
                abs(timestamp - self.cur)
                >= self._max_years_between_matches * 365 * 86400
            ):
                result_year = _datetime.datetime.fromtimestamp(wall, UTC_DT).year
                current_year = _datetime.datetime.fromtimestamp(self.cur, UTC_DT).year
                if abs(result_year - current_year) > self._max_years_between_matches:
                    raise CroniterBadDateError(
                        "failed to find a matching date within the year limit"
                    )
            if update_current:
                self.cur = timestamp
            return timestamp
        timestamp, result = self._resolve_wall(wall, is_prev)
        current_year = self.timestamp_to_datetime(self.cur).year
        if abs(result.year - current_year) > self._max_years_between_matches:
            raise CroniterBadDateError("failed to find a matching date within the year limit")
        if update_current:
            self.cur = timestamp
        return result if returns_datetime else timestamp

    def get_next(self, ret_type=None, start_time=None, update_current=True):
        if start_time is not None and self._expand_from_start_time:
            raise ValueError("start_time is not supported with expand_from_start_time")
        return self._get_next(ret_type, start_time, False, update_current)

    def get_prev(self, ret_type=None, start_time=None, update_current=True):
        return self._get_next(ret_type, start_time, True, update_current)

    def _get_n(self, count: int, ret_type: type | None, is_prev: bool):
        if count < 0:
            raise ValueError("count must be non-negative")
        ret_type = ret_type or self._ret_type
        if not isinstance(ret_type, type) or not issubclass(ret_type, (float, _datetime.datetime)):
            raise TypeError("Invalid ret_type, only 'float' or 'datetime' is acceptable.")
        if count == 0:
            return []
        if self.tzinfo is not None:
            method = self.get_prev if is_prev else self.get_next
            return [method(ret_type) for _ in range(count)]
        if count > _INT64_MAX:
            raise ValueError("count is outside the signed 64-bit range")
        result = np.empty(count, dtype=np.int64)
        table, table_addr, special, special_addr = self._ffi_buffers()
        result_addr = _buffer_address(result, np.dtype(np.int64), count, "output")
        written = lib().mcron_fill(
            table_addr,
            table.size,
            special_addr,
            special.size,
            _int64(self._wall_start(is_prev), "start time"),
            int(self._day_or),
            -1 if is_prev else 1,
            result_addr,
            result.size,
            count,
        )
        if written == INVALID_ARGUMENT:
            raise RuntimeError("Mojo kernel rejected the FFI buffer contract")
        if written != count:
            raise CroniterBadDateError("failed to fill the requested number of dates")
        self.cur = float(result[-1])
        if issubclass(ret_type, _datetime.datetime):
            return [self.timestamp_to_datetime(float(value)) for value in result]
        return [float(value) for value in result]

    def get_next_n(self, count: int, ret_type: type | None = None):
        """Return several next occurrences through one Mojo call."""
        return self._get_n(count, ret_type, False)

    def get_prev_n(self, count: int, ret_type: type | None = None):
        """Return several previous occurrences through one Mojo call."""
        return self._get_n(count, ret_type, True)

    def get_current(self, ret_type=None):
        ret_type = ret_type or self._ret_type
        if issubclass(ret_type, _datetime.datetime):
            return self.timestamp_to_datetime(self.cur)
        return self.cur

    def all_next(self, ret_type=None, start_time=None, update_current=None) -> Generator:
        try:
            while True:
                yield self._get_next(ret_type, start_time, False, update_current)
                start_time = None
        except CroniterBadDateError:
            if self._max_years_btw_matches_explicitly_set:
                return
            raise

    def all_prev(self, ret_type=None, start_time=None, update_current=None) -> Generator:
        try:
            while True:
                yield self._get_next(ret_type, start_time, True, update_current)
                start_time = None
        except CroniterBadDateError:
            if self._max_years_btw_matches_explicitly_set:
                return
            raise

    def iter(self, *args, **kwargs):
        return self.all_prev if self._is_prev else self.all_next

    def __iter__(self) -> Iterator:
        return self

    def __next__(self):
        return self._get_next()

    next = __next__

    @classmethod
    def match(
        cls,
        cron_expression,
        testdate,
        day_or=True,
        second_at_beginning=False,
        precision_in_seconds=None,
    ):
        return cls.match_range(
            cron_expression, testdate, testdate, day_or,
            second_at_beginning, precision_in_seconds,
        )

    @classmethod
    def match_range(
        cls,
        cron_expression,
        from_datetime,
        to_datetime,
        day_or=True,
        second_at_beginning=False,
        precision_in_seconds=None,
    ):
        cron = cls(
            cron_expression, to_datetime, ret_type=_datetime.datetime,
            day_or=day_or, second_at_beginning=second_at_beginning,
        )
        current = cron.get_current(_datetime.datetime)
        if current.microsecond == 0:
            current += _datetime.timedelta(microseconds=1)
        cron.set_current(current)
        try:
            previous = cron.get_prev()
        except CroniterBadDateError:
            return False
        if precision_in_seconds is None:
            precision_in_seconds = 1 if len(cron.expanded) > 5 else 60
        duration = (to_datetime - from_datetime).total_seconds() + precision_in_seconds
        return abs((current - previous).total_seconds()) < duration


def croniter_range(
    start,
    stop,
    expr_format,
    ret_type=None,
    day_or=True,
    exclude_ends=False,
    _croniter=None,
    second_at_beginning=False,
    expand_from_start_time=False,
):
    implementation = _croniter or croniter
    if type(start) is not type(stop) and not (
        isinstance(start, type(stop)) or isinstance(stop, type(start))
    ):
        raise CroniterBadTypeRangeError(
            f"The start and stop must be same type. {type(start)} != {type(stop)}"
        )
    numeric = isinstance(start, (int, float))
    if numeric:
        start, stop = (
            _datetime.datetime.fromtimestamp(value, UTC_DT).replace(tzinfo=None)
            for value in (start, stop)
        )
    if ret_type is None:
        ret_type = float if numeric else _datetime.datetime
    if not exclude_ends:
        epsilon = _datetime.timedelta(microseconds=1)
        if start < stop:
            start -= epsilon
            stop += epsilon
        else:
            start += epsilon
            stop -= epsilon
    iterator = implementation(
        expr_format,
        start,
        ret_type=_datetime.datetime,
        day_or=day_or,
        max_years_between_matches=abs(stop.year - start.year) + 1,
        second_at_beginning=second_at_beginning,
        expand_from_start_time=expand_from_start_time,
    )
    step = iterator.get_next if start < stop else iterator.get_prev
    compare = (lambda value: value < stop) if start < stop else (lambda value: value > stop)
    try:
        value = step()
        while compare(value):
            yield iterator.get_current(float) if ret_type is float else value
            value = step()
    except CroniterBadDateError:
        return
