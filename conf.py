import logging
from optparse import OptionParser

LAST_MES_COUNT = 20
EMPTY_MESSAGE = b'\n'
SERVER_PORT = 8000
SERVER_HOST = '127.0.0.1'
LIMIT_MES_HOUR = 20
PERIOD_MES_HOUR = 1


def config_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname).1s %(message)s',
        datefmt='%Y.%m.%d %H:%M:%S',
    )


def get_server_socket():
    op = OptionParser()
    op.add_option("-p", "--port", action="store", type=int, default=SERVER_PORT)
    op.add_option("-H", "--host", action="store", default=SERVER_HOST)
    (opts, args) = op.parse_args()
    return opts.host, opts.port
