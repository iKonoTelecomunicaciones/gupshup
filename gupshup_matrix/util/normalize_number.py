remove_extra_chars = str.maketrans("", "", " .,-()")


def normalize_number(number: str) -> str:
    phone = number.translate(remove_extra_chars)
    if not number.startswith("+") or not phone[1:].isdecimal():
        raise Exception("Phone number must be entered in international format")
    return phone
