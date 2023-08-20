import argparse
from bs4 import BeautifulSoup
import dateparser
import hashlib
import logging
import os.path as path
import re
from sys import stdout
import zipfile

LOG_LEVEL="INFO"

def make_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('path', help='path to data archvie')
    parser.add_argument('-s', '--start'
                        , help='start of the timeperiod to extract data for (exclusive)'
                        , default='Jan 01 1970')
    parser.add_argument('-e', '--end'
                        , help='end of the timeperiod to extract data for (inclusive)'
                        , default='Dec 31 2100') # Hope nobody is using this in 77 years
    parser.add_argument('-o', '--out', help='path to write cleaned archive to')
    
    return parser

def sha256_file(some_path):
    # shamelessly stolen
    # https://stackoverflow.com/questions/22058048/hashing-a-file-in-python
    BUFFSIZE = 64 * 1024 # 64kB
    HASH = hashlib.sha256()
    with open(some_path, 'rb') as some_file:
        while True:
            data = some_file.read(BUFFSIZE)
            if not data:
                break
            HASH.update(data)
    logging.info('SHA256({}): {}'.format(some_path, HASH.hexdigest()))

# Function to check if date is in given range
def is_date_in_range(date_string, start, end):
    parsed_date = dateparser.parse(date_string)
    logging.debug('parsed_date: {}'.format(parsed_date))
    if parsed_date is None:
        return True
    logging.debug('start: {}'.format(start))
    start_date = dateparser.parse(start)
    logging.debug('start_date: {}'.format(start_date))
    end_date = dateparser.parse(end)
    logging.debug('end_date: {}'.format(end_date))
    
    return (start_date <= parsed_date < end_date)

def delete_divs(html, start, end):
    # div classes that contain content
    entry_classes = ['_3-95', '_2pi3']

    # there are lots of different formats
    # Oct 05, 2012 4:58:09pm
    # August 3, 2021 at 10:11 AM
    # Jul 14, 2023, 5:32 PM
    # one pattern to rule them all
    ts_pattern = r'^\w+\s\d{1,2},\s\d{4},?\s(at )?\d{1,2}:\d{2}(:\d{2}|\s)\w+$'

    # make soup
    soup = BeautifulSoup(html, 'html.parser')

    # Find div tags with the specified class
    for ec in entry_classes:
        entries = soup.find_all('div', class_=ec)

        # find timestamps
        # look for div elements whose entire .text matches ts_pattern
        for e in entries:
            content_divs = e.find_all('div')
            for cd in content_divs:
                # check the length of the supposed timestamp to avoid recursion issues
                # if it's too long, it's probably a parent div that will be sub-parsed
                if len(cd.text) > 50:
                    continue
                if re.match(ts_pattern, cd.text):
                    try:
                        if not is_date_in_range(cd.text, start, end):
                            logging.info('Deleting div for date {}'.format(cd.text))
                            e.decompose()
                    except RecursionError:
                        logging.error('RecursionError encountered')
                        logging.debug('stamp.text: {}'.format(cd.text))
                        exit(1)
    return str(soup)

def get_media_srcs(html):
    srcs = []
    media_tags= ['img', 'video']
    
    soup = BeautifulSoup(html, 'html.parser')

    for element in soup.find_all(media_tags):
        src = element['src']
        # don't include images embeded in the html, 
        #  remotely loaded resources, or this one thing that doesn't exist
        if not src.startswith('data:') and not src.startswith('https://') and not src.startswith('http://') \
            and src != r'comments_and_reactions/icons/none.png' and src != '':
            srcs.append(src)
    
    return srcs

if __name__ == '__main__':
    SUFFIX = '_CLEANED'
    
    NUMERIC_LEVEL = getattr(logging, LOG_LEVEL.upper(), None)
    if not isinstance(NUMERIC_LEVEL, int):
        raise ValueError('Invalid log level: %s' % LOG_LEVEL)
    logging.basicConfig(
        stream=stdout
        ,format='%(asctime)s %(levelname)s: %(message)s'
        ,level=NUMERIC_LEVEL
    )

    # get arguments
    args = make_parser().parse_args()
    logging.debug(args)
    
    if zipfile.is_zipfile(args.path):
        logging.info('Using {} as input file'.format(args.path))
    else:
        logging.critical('Input file must be a zip archive')
        exit(1)

    # calculate the output path
    out_path = ''
    if args.out:
        if path.isdir(args.out):
            fn = path.basename(args.path)
            (base, ext) = path.splitext(fn)
            out_path = path.join(args.out, (base + SUFFIX + ext))
        else:
            out_path = args.out
    else:
        (base, ext) = path.splitext(args.path)
        out_path = base + SUFFIX + ext
    logging.info('Writing cleaned file to {}'.format(out_path))

    # get the input file hash
    sha256_file(args.path)

    # open the zip archives
    with zipfile.ZipFile(args.path, 'r') as in_zip:
        with zipfile.ZipFile(out_path, 'w') as out_zip:
            
            # find .html docs
            for item in in_zip.infolist():    
                (root,ext) = path.splitext(item.filename)
                if ext == '.html':
                    logging.info('Parsing {}'.format(item.filename))
                    with in_zip.open(item, 'r') as in_file:
                        # remove divs based on the time
                        out_html = delete_divs(in_file.read(), args.start, args.end)

                        # copy any media still needed by the clean document
                        media_srcs = get_media_srcs(out_html)
                        for src in media_srcs:
                            # check to see if we copied it already
                            try:
                                out_zip.getinfo(src)
                            except KeyError:
                                # file does not already exist, copy it
                                logging.info('Copying {} to new archive'.format(src))
                                with in_zip.open(src, 'r') as src_file:
                                    out_zip.writestr(src, src_file.read())

                        # add clened .html document to out_zip
                        out_zip.writestr(item, out_html)

    # get the output file hash
    sha256_file(out_path)
