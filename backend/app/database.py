from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        pragma_conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        pragma_conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        pragma_conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")

        columns = conn.execute(text("PRAGMA table_info(portfolio_positions);")).fetchall()
        column_names = {row[1] for row in columns}
        if "current_price" not in column_names:
            conn.execute(text("ALTER TABLE portfolio_positions ADD COLUMN current_price FLOAT DEFAULT 0;"))
            conn.execute(text("UPDATE portfolio_positions SET current_price = avg_cost WHERE current_price IS NULL OR current_price = 0;"))

        user_rule_columns = conn.execute(text("PRAGMA table_info(user_rules);")).fetchall()
        user_rule_names = {row[1] for row in user_rule_columns}
        if "buy_zone_extra_margin" not in user_rule_names:
            conn.execute(text("ALTER TABLE user_rules ADD COLUMN buy_zone_extra_margin FLOAT DEFAULT 0.01;"))
        conn.execute(text("UPDATE user_rules SET buy_zone_extra_margin = 0.01 WHERE buy_zone_extra_margin IS NULL;"))
        if "allocation_balance_tolerance" not in user_rule_names:
            conn.execute(text("ALTER TABLE user_rules ADD COLUMN allocation_balance_tolerance FLOAT DEFAULT 0.02;"))
        conn.execute(
            text(
                "UPDATE user_rules SET allocation_balance_tolerance = 0.02 "
                "WHERE allocation_balance_tolerance IS NULL;"
            )
        )
        if "target_attack_stock_ratio" not in user_rule_names:
            conn.execute(text("ALTER TABLE user_rules ADD COLUMN target_attack_stock_ratio FLOAT DEFAULT 0.34;"))
        if "target_balance_stock_ratio" not in user_rule_names:
            conn.execute(text("ALTER TABLE user_rules ADD COLUMN target_balance_stock_ratio FLOAT DEFAULT 0.33;"))
        if "target_defense_stock_ratio" not in user_rule_names:
            conn.execute(text("ALTER TABLE user_rules ADD COLUMN target_defense_stock_ratio FLOAT DEFAULT 0.33;"))
        conn.execute(
            text(
                "UPDATE user_rules SET target_attack_stock_ratio = 0.34 "
                "WHERE target_attack_stock_ratio IS NULL;"
            )
        )
        conn.execute(
            text(
                "UPDATE user_rules SET target_balance_stock_ratio = 0.33 "
                "WHERE target_balance_stock_ratio IS NULL;"
            )
        )
        conn.execute(
            text(
                "UPDATE user_rules SET target_defense_stock_ratio = 0.33 "
                "WHERE target_defense_stock_ratio IS NULL;"
            )
        )
        conn.execute(
            text(
                "UPDATE user_rules "
                "SET target_attack_stock_ratio = 0.34, target_balance_stock_ratio = 0.33, target_defense_stock_ratio = 0.33 "
                "WHERE COALESCE(target_attack_stock_ratio, 0) + COALESCE(target_balance_stock_ratio, 0) + COALESCE(target_defense_stock_ratio, 0) <= 0;"
            )
        )
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
