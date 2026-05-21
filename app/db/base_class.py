from sqlalchemy.ext.declarative import declarative_base, declared_attr


class CustomBase:
    """Base class for all database models"""

    # Generate __tablename__ automatically based on class name
    @declared_attr  # type: ignore
    def __tablename__(cls) -> str:
        return cls.__name__.lower()  # type: ignore


# Create the base class for all models
Base = declarative_base(cls=CustomBase)
