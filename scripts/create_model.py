import sys
from pathlib import Path


def to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("_"))


TEMPLATE_MODELS = """from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class {class_name}(Base):
    __tablename__ = "{name}"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
"""


def main():

    if len(sys.argv) < 2:
        print("Usage: python scripts/create_model.py <feature_name>")
        sys.exit(1)

    feature_name = sys.argv[1]
    class_name = to_pascal_case(feature_name)

    root = Path(__file__).resolve().parents[1]

    feature_dir = root / "backend" / "app" / "features" / feature_name

    if not feature_dir.exists():
        print(f"Feature '{feature_name}' does not exist.")
        sys.exit(1)

    model_file = feature_dir / "models.py"

    if model_file.exists():
        print(f"models.py already exists for '{feature_name}'")
        sys.exit(1)

    model_file.write_text(
        TEMPLATE_MODELS.format(
            name=feature_name,
            class_name=class_name,
        )
    )

    print(f"Created models.py for feature '{feature_name}'")


if __name__ == "__main__":
    main()
