import asyncio
import logging

import aioconsole as aioconsole

from conf import config_logging, get_server_socket

logger = logging.getLogger(__name__)
lock = asyncio.Lock()


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
            # Если в переданных файлах есть файл, то определяем его начало и начинаем получать оставшуюся часть
            if '/file' in data.decode():
                mes_with_file = data.decode().split('/file')
                file_part_1 = mes_with_file[-1]
                mes = mes_with_file[0]
                print(mes)
                file = await self._read_file()
                # пишем в файл в отдельном потоке
                await asyncio.to_thread(self._write_file, file_part_1.encode() + file)
            else:
                print(data.decode())

    async def _read_file(self):
        # вычитываем файл чанками
        data = bytearray()
        while True:
            chunk = await self.reader.read(1024)
            data += chunk
            if len(chunk) < 1024:
                break

        return data

    @staticmethod
    def _write_file(file):
        # тут хардкод просто для примера
        with open('tmp/2', 'wb') as f:
            f.write(file)

    async def start(self):
        while True:
            if self.read_task.done():
                break
            message = await aioconsole.ainput('>')
            self.writer.write(message.encode())
            await self.writer.drain()
            # Если нужно отправить файл
            if message.startswith('/file'):
                filepath = message.split()[1]
                file = await asyncio.to_thread(self._open_file, filepath)
                self.writer.write(file)
                await self.writer.drain()

        self.writer.close()
        logger.info('Сервер разорвал соединение')

    @staticmethod
    def _open_file(filename):
        try:
            with open(filename, 'rb') as f:
                return f.read()
        except FileNotFoundError:
            return None


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
