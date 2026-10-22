"""PII masking for resident data (LGPD-minded defaults).

Residents' phone (`contato`) and CPF are personal data under Brazil's LGPD. Tools
return them masked unless the caller's role holds the `pii` permission *and* the
call explicitly asks for `reveal_pii=true`. Masking keeps just enough to let a
doorman disambiguate two residents ("the one whose phone ends in 4321").
"""

import re


def mask_phone(value: str | None) -> str | None:
    """'(11) 98765-4321' -> '(**) *****-4321'; 'ana@x.com' -> 'a***@x.com'."""
    if not value:
        return value
    if "@" in value:
        user, _, domain = value.partition("@")
        return f"{user[:1]}***@{domain}"
    digits_seen = 0
    total_digits = sum(c.isdigit() for c in value)
    out = []
    for c in value:
        if c.isdigit():
            digits_seen += 1
            out.append(c if digits_seen > total_digits - 4 else "*")
        else:
            out.append(c)
    return "".join(out)


def mask_cpf(value: str | None) -> str | None:
    """'12345678909' -> '***.***.***-09' (only the check digits survive)."""
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    return f"***.***.***-{digits[-2:]}" if len(digits) >= 2 else "***"


def format_cpf(value: str | None) -> str | None:
    if not value:
        return value
    d = re.sub(r"\D", "", value)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else value
