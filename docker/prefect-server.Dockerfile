# flare-prefect-server: the official Prefect 3.8.7 server with SQLAlchemy pinned to the 2.0 line.
# Why: the official image ships SQLAlchemy 2.1.1, whose changed bulk-insert API makes Prefect's scheduler fail on every
# pass ("Can't evaluate bulk DML statement" in schedule_deployments), so scheduled deployments never created runs
# (found 2026-11-16 on the AWS server: 0 flow runs). With SQLAlchemy 2.0.x the scheduler works.
FROM prefecthq/prefect:3.8.7-python3.12
RUN pip install --no-cache-dir "sqlalchemy==2.0.57" \
 && python -c "import sqlalchemy, prefect; assert sqlalchemy.__version__ == '2.0.57'; print('prefect', prefect.__version__, 'sqlalchemy', sqlalchemy.__version__)"
LABEL org.opencontainers.image.source="https://github.com/veenaphadtare12-ux/aditya-l1-solar-flare-nowcasting-forecasting" \
      org.opencontainers.image.title="flare-prefect-server"
