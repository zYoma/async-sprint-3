import asyncio
from optparse import OptionParser
import aioconsole as aioconsole
import threading
import logging
import sys
import asyncio
from conf import get_server_socket, config_logging
from io import BytesIO


logger = logging.getLogger(__name__)


class Client:

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        # запускаем чтение из stream в фоне
        self.read_task = asyncio.create_task(self._read())

    async def _read(self):
        while True:
            data = await self.reader.read(1024)
            if not data:
                break

            print(data.decode())

    async def start(self):
        while True:
            if self.read_task.done():
                break
            message = await aioconsole.ainput('>')
            self.writer.write(message.encode())
            # Если нужно отправить файл
            if message.startswith('/file'):
                filepath = message.split()[1]
                file = await asyncio.to_thread(self._open_file, filepath)
                print(len(file))
                for chunk in self._chunked(1024, file):
                    self.writer.write(chunk)

                # self.writer.write(b'end-file')

        self.writer.close()
        logger.info('Сервер разорвал соединение')

    @staticmethod
    def _open_file(filename):
        try:
            with open(filename, 'rb') as f:
                return f.read()
        except FileNotFoundError:
            return None

    @staticmethod
    def _chunked(size, source):
        for i in range(0, len(source), size):
            yield source[i:i + size]


async def main(host, port):
    reader, writer = await asyncio.open_connection(host, port)
    client = Client(reader, writer)
    await client.start()


if __name__ == '__main__':
    config_logging()
    host, port = get_server_socket()
    try:
        asyncio.run(main(host, port))
    except KeyboardInterrupt:
        pass
