"""
Create licenses and target databases for the tests to run against.
"""

import datetime
import os
import sys
import textwrap
from pathlib import Path

import vws_web_tools
from selenium import webdriver

email_address = os.environ["VWS_EMAIL_ADDRESS"]
password = os.environ["VWS_PASSWORD"]
new_secrets_dir = Path(__file__).parent / "vuforia_secrets"
new_secrets_dir.mkdir(exist_ok=True)

num_databases = 100
start_number = len(list(new_secrets_dir.glob("*")))
driver = webdriver.Safari()

for i in range(start_number, num_databases):
    sys.stdout.write(f"Creating database {i}\n")
    time = datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d-%H-%M-%S")
    license_name = f"my-license-{time}"
    database_name = f"my-database-{time}"

    vws_web_tools.log_in(
        driver=driver,
        email_address=email_address,
        password=password,
    )
    vws_web_tools.wait_for_logged_in(driver=driver)
    vws_web_tools.create_license(driver=driver, license_name=license_name)

    vws_web_tools.create_database(
        driver=driver,
        database_name=database_name,
        license_name=license_name,
    )

    database_details = vws_web_tools.get_database_details(
        driver=driver,
        database_name=database_name,
    )

    file_contents = textwrap.dedent(
        f"""\
        VUFORIA_TARGET_MANAGER_DATABASE_NAME={database_details["database_name"]},
        VUFORIA_SERVER_ACCESS_KEY={database_details["server_access_key"]},
        VUFORIA_SERVER_SECRET_KEY={database_details["server_secret_key"]},
        VUFORIA_CLIENT_ACCESS_KEY={database_details["client_access_key"]},
        VUFORIA_CLIENT_SECRET_KEY={database_details["client_secret_key"]},

        INACTIVE_VUFORIA_TARGET_MANAGER_DATABASE_NAME={os.environ["INACTIVE_VUFORIA_TARGET_MANAGER_DATABASE_NAME"]},
        INACTIVE_VUFORIA_SERVER_ACCESS_KEY={os.environ["INACTIVE_VUFORIA_SERVER_ACCESS_KEY"]},
        INACTIVE_VUFORIA_SERVER_SECRET_KEY={os.environ["INACTIVE_VUFORIA_SERVER_SECRET_KEY"]},
        INACTIVE_VUFORIA_CLIENT_ACCESS_KEY={os.environ["INACTIVE_VUFORIA_CLIENT_ACCESS_KEY"]},
        INACTIVE_VUFORIA_CLIENT_SECRET_KEY={os.environ["INACTIVE_VUFORIA_CLIENT_SECRET_KEY"]},
        """,
    )

    file_name = f"vuforia_secrets_{i}.env"
    (new_secrets_dir / file_name).write_text(file_contents)
