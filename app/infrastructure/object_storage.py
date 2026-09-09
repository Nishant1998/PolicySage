from functools import lru_cache

from app.core.config import get_settings
from app.core.observability import span


@lru_cache(maxsize=1)
def object_store():
    import boto3
    from botocore.config import Config

    settings = get_settings()
    if not all((settings.kb_s3_endpoint, settings.kb_s3_region, settings.kb_s3_bucket,
                settings.kb_s3_access_key_id.get_secret_value(),
                settings.kb_s3_secret_access_key.get_secret_value())):
        raise RuntimeError("Configure the managed KB object storage settings.")
    return boto3.client(
        "s3", endpoint_url=settings.kb_s3_endpoint, region_name=settings.kb_s3_region,
        aws_access_key_id=settings.kb_s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.kb_s3_secret_access_key.get_secret_value(),
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4",
                      connect_timeout=10, read_timeout=60, retries={"max_attempts": 3}),
    )


def upload_pdf(key, content):
    bucket = get_settings().kb_s3_bucket
    client = object_store()
    with span("object_storage_upload") as trace:
        trace["bytes"] = len(content)
        client.put_object(Bucket=bucket, Key=key, Body=content, ContentType="application/pdf",
                          IfNoneMatch="*")
        if client.head_object(Bucket=bucket, Key=key)["ContentLength"] != len(content):
            raise RuntimeError("Stored PDF size does not match the upload.")


def download_pdf(key, limit):
    with span("object_storage_download") as trace:
        result = object_store().get_object(Bucket=get_settings().kb_s3_bucket, Key=key)
        with result["Body"] as body:
            content = body.read(limit)
        trace["bytes"] = len(content)
    return content


def delete_pdf(key):
    object_store().delete_object(Bucket=get_settings().kb_s3_bucket, Key=key)


def signed_pdf_url(object_key):
    return object_store().generate_presigned_url(
        "get_object", Params={"Bucket": get_settings().kb_s3_bucket, "Key": object_key}, ExpiresIn=60,
    )
