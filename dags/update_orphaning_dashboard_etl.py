from airflow import DAG
from airflow.contrib.hooks.aws_hook import AwsHook
from airflow.contrib.hooks.gcp_api_base_hook import GoogleCloudBaseHook
from airflow.operators.subdag_operator import SubDagOperator
from datetime import datetime, timedelta

from utils.constants import DS_WEEKLY
from utils.dataproc import moz_dataproc_pyspark_runner

"""

The following WTMO connections are needed in order for this job to run:
conn - google_cloud_airflow_dataproc
conn - aws_dev_telemetry_public_analysis_2_rw
"""

default_args = {
    "owner": "akomar@mozilla.com",
    "depends_on_past": False,
    "start_date": datetime(2019, 10, 12),
    "email": ["telemetry-alerts@mozilla.com", "rstrong@mozilla.com", "akomar@mozilla.com"],
    "email_on_failure": True,
    "email_on_retry": True,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}

# run every Monday to maintain compatibility with legacy ATMO schedule
dag = DAG("update_orphaning_dashboard_etl", default_args=default_args, schedule_interval="0 2 * * MON")

# Unsalted cluster name so subsequent runs fail if the cluster name exists
cluster_name = 'app-update-out-of-date-dataproc-cluster'

# Defined in Airflow's UI -> Admin -> Connections
gcp_conn_id = 'google_cloud_airflow_dataproc'
connection = GoogleCloudBaseHook(gcp_conn_id=gcp_conn_id)

# Required to write json output back to s3://telemetry-public-analysis-2/app-update/data/out-of-date/
write_aws_conn_id='aws_dev_telemetry_public_analysis_2_rw'
aws_access_key, aws_secret_key, session = AwsHook(write_aws_conn_id).get_credentials()

crash_report_parquet = SubDagOperator(
    task_id="update_orphaning_dashboard_etl",
    dag=dag,
    subdag = moz_dataproc_pyspark_runner(
        parent_dag_name=dag.dag_id,
        dag_name="update_orphaning_dashboard_etl",
        default_args=default_args,
        cluster_name=cluster_name,
        job_name="update_orphaning_dashboard_etl",
        python_driver_code="gs://moz-fx-data-prod-airflow-dataproc-artifacts/jobs/update_orphaning_dashboard_etl.py",
        init_actions_uris=["gs://dataproc-initialization-actions/python/pip-install.sh"],
        additional_metadata={'PIP_PACKAGES': "google-cloud-bigquery==1.20.0 google-cloud-storage==1.19.1 boto3==1.9.253"},
        additional_properties={"spark:spark.jars.packages": "org.apache.spark:spark-avro_2.11:2.4.3"},
        py_args=[
            "--run-date", DS_WEEKLY,
            "--gcs-bucket", "moz-fx-data-derived-datasets-analysis",
            "--gcs-prefix", "update-orphaning-airflow",
            "--s3-output-bucket", "telemetry-public-analysis-2",
            "--s3-output-path", "app-update/data/out-of-date/",
            "--aws-access-key-id", aws_access_key,
            "--aws-secret-access-key", aws_secret_key
        ],
        idle_delete_ttl='14400',
        num_workers=20,
        worker_machine_type='n1-standard-8',
        gcp_conn_id=gcp_conn_id)
)