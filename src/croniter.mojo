comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]

comptime MINUTE = 0
comptime HOUR = 60
comptime DAY = 84
comptime MONTH = 116
comptime DOW = 129
comptime SECOND = 136
comptime YEAR = 196
comptime NO_MATCH = Int64(-9223372036854775807)
comptime INVALID_ARGUMENT = Int64(-9223372036854775806)
comptime TABLE_LEN = 326
comptime SPECIAL_LEN = 12


def floor_div(a: Int, b: Int) -> Int:
    if a >= 0:
        return a // b
    return -((-a + b - 1) // b)


def is_leap(year: Int) -> Bool:
    return year % 400 == 0 or (year % 4 == 0 and year % 100 != 0)


def month_days(year: Int, month: Int) -> Int:
    if month == 2:
        return 29 if is_leap(year) else 28
    if month == 4 or month == 6 or month == 9 or month == 11:
        return 30
    return 31


def days_from_civil(year: Int, month: Int, day: Int) -> Int:
    var y = year - (1 if month <= 2 else 0)
    var era = floor_div(y, 400)
    var yoe = y - era * 400
    var mp = month + (-3 if month > 2 else 9)
    var doy = (153 * mp + 2) // 5 + day - 1
    var doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(days: Int) -> Tuple[Int, Int, Int]:
    var z = days + 719468
    var era = floor_div(z, 146097)
    var doe = z - era * 146097
    var yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    var y = yoe + era * 400
    var doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    var mp = (5 * doy + 2) // 153
    var day = doy - (153 * mp + 2) // 5 + 1
    var month = mp + (3 if mp < 10 else -9)
    y += 1 if month <= 2 else 0
    return (y, month, day)


def epoch_seconds(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int) -> Int:
    return days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second


def allowed(table: BPtr, base: Int, value: Int) -> Bool:
    return table[base + value] != UInt8(0)


def day_allowed(
    table: BPtr,
    special: IPtr,
    year: Int,
    month: Int,
    day: Int,
    dow: Int,
    day_or: Bool,
) -> Bool:
    var dom_all = special[0] != 0
    var dow_all = special[1] != 0
    var dom_ok = allowed(table, DAY, day)
    if special[2] != 0 and day == month_days(year, month):
        dom_ok = True
    var nearest = Int(special[3])
    if nearest > 0:
        var target = nearest
        var target_dow = (days_from_civil(year, month, target) + 4) % 7
        if target_dow == 6:
            target = target - 1 if target > 1 else target + 2
        elif target_dow == 0:
            target = target + 1 if target < month_days(year, month) else target - 2
        dom_ok = day == target

    var dow_ok = allowed(table, DOW, dow)
    if dow_ok:
        var nth_mask = Int(special[4 + dow])
        if nth_mask != 0:
            var nth = (day - 1) // 7 + 1
            var is_last = day + 7 > month_days(year, month)
            dow_ok = ((nth_mask >> nth) & 1) != 0 or (
                ((nth_mask >> 6) & 1) != 0 and is_last
            )

    if special[11] != 0:
        return dow_ok if day_or else (dom_ok and dow_ok)
    if nearest > 0:
        return dom_ok if day_or else (dom_ok and dow_ok)
    if dom_all:
        return dow_ok
    if dow_all:
        return dom_ok
    return (dom_ok or dow_ok) if day_or else (dom_ok and dow_ok)


def next_allowed(table: BPtr, base: Int, current: Int, maximum: Int) -> Int:
    for value in range(current, maximum + 1):
        if allowed(table, base, value):
            return value
    return -1


def prev_allowed(table: BPtr, base: Int, current: Int, minimum: Int) -> Int:
    var value = current
    while value >= minimum:
        if allowed(table, base, value):
            return value
        value -= 1
    return -1


def find_next(table: BPtr, special: IPtr, start: Int, day_or: Bool) -> Int64:
    var ts = start + 1
    for _ in range(100000):
        var days = floor_div(ts, 86400)
        var sod = ts - days * 86400
        var date = civil_from_days(days)
        var year = date[0]
        var month = date[1]
        var day = date[2]
        var hour = sod // 3600
        var minute = (sod % 3600) // 60
        var second = sod % 60

        if year < 1970:
            ts = epoch_seconds(1970, 1, 1, 0, 0, 0)
            continue
        if year > 2099:
            return NO_MATCH
        if not allowed(table, YEAR, year - 1970):
            var next_year = next_allowed(table, YEAR, year - 1969, 129)
            if next_year < 0:
                return NO_MATCH
            ts = epoch_seconds(1970 + next_year, 1, 1, 0, 0, 0)
            continue

        if not allowed(table, MONTH, month):
            var next_month = next_allowed(table, MONTH, month + 1, 12)
            if next_month >= 0:
                ts = epoch_seconds(year, next_month, 1, 0, 0, 0)
            else:
                ts = epoch_seconds(year + 1, 1, 1, 0, 0, 0)
            continue

        var dow = (days + 4) % 7
        if not day_allowed(table, special, year, month, day, dow, day_or):
            ts = (days + 1) * 86400
            continue

        if not allowed(table, HOUR, hour):
            var next_hour = next_allowed(table, HOUR, hour + 1, 23)
            if next_hour >= 0:
                ts = days * 86400 + next_hour * 3600
            else:
                ts = (days + 1) * 86400
            continue

        if not allowed(table, MINUTE, minute):
            var next_minute = next_allowed(table, MINUTE, minute + 1, 59)
            if next_minute >= 0:
                ts = days * 86400 + hour * 3600 + next_minute * 60
            else:
                ts = days * 86400 + (hour + 1) * 3600
            continue

        if not allowed(table, SECOND, second):
            var next_second = next_allowed(table, SECOND, second + 1, 59)
            if next_second >= 0:
                ts = days * 86400 + hour * 3600 + minute * 60 + next_second
            else:
                ts = days * 86400 + hour * 3600 + (minute + 1) * 60
            continue
        return Int64(ts)
    return NO_MATCH


def find_prev(table: BPtr, special: IPtr, start: Int, day_or: Bool) -> Int64:
    var ts = start - 1
    for _ in range(100000):
        var days = floor_div(ts, 86400)
        var sod = ts - days * 86400
        var date = civil_from_days(days)
        var year = date[0]
        var month = date[1]
        var day = date[2]
        var hour = sod // 3600
        var minute = (sod % 3600) // 60
        var second = sod % 60

        if year > 2099:
            ts = epoch_seconds(2099, 12, 31, 23, 59, 59)
            continue
        if year < 1970:
            return NO_MATCH
        if not allowed(table, YEAR, year - 1970):
            var prev_year = prev_allowed(table, YEAR, year - 1971, 0)
            if prev_year < 0:
                return NO_MATCH
            var py = 1970 + prev_year
            ts = epoch_seconds(py, 12, 31, 23, 59, 59)
            continue

        if not allowed(table, MONTH, month):
            var prev_month = prev_allowed(table, MONTH, month - 1, 1)
            if prev_month >= 0:
                var last_day = month_days(year, prev_month)
                ts = epoch_seconds(year, prev_month, last_day, 23, 59, 59)
            else:
                ts = epoch_seconds(year, 1, 1, 0, 0, 0) - 1
            continue

        var dow = (days + 4) % 7
        if not day_allowed(table, special, year, month, day, dow, day_or):
            ts = days * 86400 - 1
            continue

        if not allowed(table, HOUR, hour):
            var prev_hour = prev_allowed(table, HOUR, hour - 1, 0)
            if prev_hour >= 0:
                ts = days * 86400 + prev_hour * 3600 + 3599
            else:
                ts = days * 86400 - 1
            continue

        if not allowed(table, MINUTE, minute):
            var prev_minute = prev_allowed(table, MINUTE, minute - 1, 0)
            if prev_minute >= 0:
                ts = days * 86400 + hour * 3600 + prev_minute * 60 + 59
            else:
                ts = days * 86400 + hour * 3600 - 1
            continue

        if not allowed(table, SECOND, second):
            var prev_second = prev_allowed(table, SECOND, second - 1, 0)
            if prev_second >= 0:
                ts = days * 86400 + hour * 3600 + minute * 60 + prev_second
            else:
                ts = days * 86400 + hour * 3600 + minute * 60 - 1
            continue
        return Int64(ts)
    return NO_MATCH


@export("mcron_next")
def mcron_next(
    table_addr: Int,
    table_len: Int,
    special_addr: Int,
    special_len: Int,
    start: Int64,
    day_or: Int,
) abi("C") -> Int64:
    if table_addr == 0 or special_addr == 0:
        return INVALID_ARGUMENT
    if table_len != TABLE_LEN or special_len != SPECIAL_LEN:
        return INVALID_ARGUMENT
    var table = BPtr(unsafe_from_address=table_addr)
    var special = IPtr(unsafe_from_address=special_addr)
    return find_next(table, special, Int(start), day_or != 0)


@export("mcron_prev")
def mcron_prev(
    table_addr: Int,
    table_len: Int,
    special_addr: Int,
    special_len: Int,
    start: Int64,
    day_or: Int,
) abi("C") -> Int64:
    if table_addr == 0 or special_addr == 0:
        return INVALID_ARGUMENT
    if table_len != TABLE_LEN or special_len != SPECIAL_LEN:
        return INVALID_ARGUMENT
    var table = BPtr(unsafe_from_address=table_addr)
    var special = IPtr(unsafe_from_address=special_addr)
    return find_prev(table, special, Int(start), day_or != 0)


@export("mcron_fill")
def mcron_fill(
    table_addr: Int,
    table_len: Int,
    special_addr: Int,
    special_len: Int,
    start: Int64,
    day_or: Int,
    direction: Int,
    dst_addr: Int,
    dst_len: Int,
    count: Int,
) abi("C") -> Int64:
    if table_addr == 0 or special_addr == 0:
        return INVALID_ARGUMENT
    if table_len != TABLE_LEN or special_len != SPECIAL_LEN:
        return INVALID_ARGUMENT
    if count < 0 or dst_len < count or (count > 0 and dst_addr == 0):
        return INVALID_ARGUMENT
    var table = BPtr(unsafe_from_address=table_addr)
    var special = IPtr(unsafe_from_address=special_addr)
    if count == 0:
        return 0
    var dst = IPtr(unsafe_from_address=dst_addr)
    var current = start
    for i in range(count):
        var value = (
            find_next(table, special, Int(current), day_or != 0)
            if direction >= 0
            else find_prev(table, special, Int(current), day_or != 0)
        )
        if value == NO_MATCH:
            return Int64(i)
        dst[i] = value
        current = value
    return Int64(count)
