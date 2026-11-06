"""One command each for seed, reset, start and a configuration check.

    python -m app.cli seed     # create tables if needed and load the demo data (only into an empty database)
    python -m app.cli reset    # drop everything and reload the demo data
    python -m app.cli start    # run the web app on http://127.0.0.1:8000
    python -m app.cli check    # say which database is configured and whether it answers
"""
import sys

from sqlalchemy import inspect, select

from . import config, db, models, seed


def _check():
    url = config.DATABASE_URL
    shown = url.split("@")[-1] if "@" in url else url
    try:
        with db.engine.connect() as c:
            c.execute(select(1))
        print(f"Database OK: {db.engine.dialect.name} ({shown})")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Cannot reach the database at {shown}: {e.__class__.__name__}: {e}")
        if url.startswith("postgresql"):
            print("Fix: start PostgreSQL and create the database. See docs/SETUP_POSTGRES.md, step 2.")
        return False


def main(argv=None):
    cmd = (argv or sys.argv[1:] or ["help"])[0]
    if cmd == "check":
        sys.exit(0 if _check() else 1)
    if cmd in ("seed", "reset", "start") and not _check():
        sys.exit(1)
    if cmd == "reset":
        seed.reset()
        print("Reset: demo data reloaded. Open http://%s:%s/login" % (config.HOST, config.PORT))
    elif cmd == "seed":
        if "cases" in inspect(db.engine).get_table_names():
            with db.SessionLocal() as s:
                if s.scalar(select(models.Case)) is not None:
                    print("Database already has data. Use `reset` to start over.")
                    return
        seed.reset()
        print("Seeded the demo data.")
    elif cmd == "start":
        import uvicorn
        if "cases" not in inspect(db.engine).get_table_names():
            seed.reset()
            print("First run: seeded the demo data.")
        print(f"Fieldwise running at http://{config.HOST}:{config.PORT}  (Ctrl+C to stop)")
        uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
