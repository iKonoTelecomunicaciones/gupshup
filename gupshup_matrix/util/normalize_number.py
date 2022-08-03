remove_extra_chars = str.maketrans("", "", " .,-()")


def normalize_number(number: str) -> str:
    phone = number.translate(remove_extra_chars)
    number = number if number.startswith("+") else f"+{number}"
    if not phone[1:].isdecimal():
        raise Exception("Phone number must be entered in international format")
    return phone
