from obs import ObsClient
import os

ak = os.getenv("AccessKeyID")
sk = os.getenv("SecretAccessKey")
server = os.getenv("ReportStorageServer")
obsClient = ObsClient(access_key_id=ak, secret_access_key=sk, server=server)

def upload_file(bucket_name, object_key, file_path):
    try:
        resp = obsClient.putFile(bucketName=bucket_name, objectKey=object_key, file_path=file_path)
        if resp.status < 300:
            print(f'File {file_path} uploaded successfully')
        else:
            print(f'Failed to upload {file_path}, status: {resp.status}')
        return True
    except Exception as e:
        print(f'Failed to upload {file_path}: {str(e)}')
        return False
    
def get_signed_url(bucket_name, object_key, expires=600):
    try:
        resp = obsClient.createSignedUrl('GET', bucket_name, object_key, expires=expires)
        return resp.signedUrl
    except Exception as e:
        print(f'Failed to generate signed URL: {str(e)}')
        return None