def format_direction_label(name: str, seats: int | None) -> str:
    if seats is None:
        return name
    return f"{name} ({seats} мест)"
