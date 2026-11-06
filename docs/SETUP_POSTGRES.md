# Set up PostgreSQL (free)

Fieldwise runs on PostgreSQL 14 or newer. If you just want to look around, skip this page and use `make offline` (SQLite).

## 1. Install PostgreSQL

| System | Command |
| --- | --- |
| macOS (Homebrew) | `brew install postgresql@16 && brew services start postgresql@16` |
| Ubuntu or Debian | `sudo apt install postgresql && sudo systemctl start postgresql` |
| Windows | Install from [postgresql.org/download](https://www.postgresql.org/download/windows/) and keep the default port 5432 |
| Docker | `docker run -d --name fieldwise-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16` |

## 2. Create a user and databases

Open a PostgreSQL prompt (`psql postgres` on macOS, `sudo -u postgres psql` on Linux, `docker exec -it fieldwise-pg psql -U postgres` for Docker) and run:

```sql
CREATE USER fieldwise PASSWORD 'fieldwise';
CREATE DATABASE fieldwise OWNER fieldwise;
CREATE DATABASE fieldwise_test OWNER fieldwise;  -- optional, for running the tests on PostgreSQL
```

Pick your own password if this machine is shared, and use it in step 3.

## 3. Point Fieldwise at it

```bash
cp .env.example .env
```

`.env` already contains:

```
DATABASE_URL=postgresql+psycopg://fieldwise:fieldwise@127.0.0.1:5432/fieldwise
```

`.env` is git-ignored, so your password stays on your machine.

## 4. Check, seed and start

```bash
make check   # "Database OK: postgresql (127.0.0.1:5432/fieldwise)"
make reset   # create tables and load the demo data
make start   # http://127.0.0.1:8000
```

## 5. Run the tests on PostgreSQL (optional)

```bash
FIELDWISE_TEST_DATABASE_URL=postgresql+psycopg://fieldwise:fieldwise@127.0.0.1:5432/fieldwise_test make test
```

This also runs the true parallel-write test, which needs PostgreSQL. The test database is wiped and reseeded for every test, so never point it at data you want to keep.
