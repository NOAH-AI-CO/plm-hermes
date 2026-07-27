import os
import urllib.parse

class DownloaderHelper:

    def doi_to_filename(self, doi: str, file_type: str = '.pdf'):
        # Specify characters that should NOT be percent-encoded.
        # By default, quote() encodes spaces and other special characters.
        # We want to keep alphanumerics, hyphens, dots, and underscores as they are.
        # Crucially, we are NOT listing '/' or ':' as safe, so they will be encoded.
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        encoded_doi = urllib.parse.quote(doi, safe=safe_chars)
        return encoded_doi + file_type

    def filename_to_doi(self, filename: str, file_type: str = '.pdf'):
        if filename.endswith(file_type):
            encoded_doi = filename[:-len(file_type)]
        else:
            encoded_doi = filename

        original_doi = urllib.parse.unquote(encoded_doi)
        return original_doi

    def check_local_file(self, filename: str):
        return os.path.isfile(filename)

