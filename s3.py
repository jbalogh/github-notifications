#!/usr/bin/env python
import os

from boto.s3.connection import S3Connection
from boto.s3.key import Key


KEY = os.environ['AWS_KEY']
SECRET_KEY = os.environ['AWS_SECRET_KEY']


def main():
    cxn = S3Connection(KEY, SECRET_KEY)
    bucket = cxn.create_bucket('github-notifications')
    print bucket
    bucket.set_acl('public-read')

    for filename in os.listdir('static'):
        key = Key(bucket)
        key.key = filename
        key.set_contents_from_filename('static/' + filename)
        key.set_acl('public-read')
        print 'Added', filename, key



if __name__ == '__main__':
    main()
