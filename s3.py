#!/usr/bin/env python
import os
import tempfile

from boto.s3.connection import S3Connection
from boto.s3.key import Key


KEY = os.environ['AWS_KEY']
SECRET_KEY = os.environ['AWS_SECRET_KEY']

DEFLATE = ('.css', '.js')


def main():
    cxn = S3Connection(KEY, SECRET_KEY)
    bucket = cxn.create_bucket('github-notifications')
    print bucket
    bucket.set_acl('public-read')

    for filename in os.listdir('static'):
        key = Key(bucket)
        key.key = filename
        path = 'static/' + filename

        suffix = os.path.splitext(filename)[1]
        if suffix in DEFLATE:
            _, tmp = tempfile.mkstemp(suffix)
            os.system('gzip -c %s > %s' % (path, tmp))
            key.set_metadata('Content-Encoding', 'gzip')
            key.set_contents_from_filename(tmp)
            os.unlink(tmp)
        else:
            key.set_contents_from_filename(path)

        key.set_acl('public-read')
        print 'Added', filename, key, key.metadata



if __name__ == '__main__':
    main()
