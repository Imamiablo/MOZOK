from mozok.db.session import engine, Base
from mozok.db import models  # noqa: F401 - imports models so SQLAlchemy sees them
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401


def main():
    Base.metadata.create_all(bind=engine)
    print("Mozok database tables created.")


if __name__ == "__main__":
    main()
