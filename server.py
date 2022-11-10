
import asyncio
import logging
from asyncio.streams import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import datetime, timedelta

from conf import (EMPTY_MESSAGE, LAST_MES_COUNT, LIMIT_MES_HOUR,
                  PERIOD_MES_HOUR, config_logging, get_server_socket)

logger = logging.getLogger(__name__)


def binary_search(list, item):
    low = 0
    high = len(list) - 1

    while low <= high:
        mid = (low + high) // 2
        guess = list[mid]
        if guess == item:
            return mid
        if guess > item:
            high = mid - 1
        else:
            low = mid + 1
    return None


@dataclass
class Message:
    login: str
    message: str
    date: datetime


class Server:
    def __init__(self):
        self.clients = dict()  # Словарь картежей с клиентскими (reader, writer)
        self.root_chat: list[Message] = list()
        self.client_ref = dict()
        self.private_chats = dict()  # {id клиента: [{'id': id собеседника, 'mes': [список сообщений], last_read: index}]

    async def _init_client(self, reader: StreamReader, writer: StreamWriter):
        # идентифицируем юзера по порту к которому он подключился и сохраняем данные о нем
        _, client_id = writer.get_extra_info('peername')
        self.clients[client_id] = (reader, writer)
        # просим пользователя представиться
        await self._send_data('Введите логин', client_id, from_user='server')
        login = await reader.read(1024)
        login = login.decode()
        self.clients[login] = self.clients.pop(client_id)

        # Отправляет подключенному юзеру последние сообщения общего чата
        last_message = self.root_chat[-LAST_MES_COUNT:]
        [await self._send_data(mes.message, login, from_user=mes.login) for mes in last_message]

        return login

    async def client_connected(self, reader: StreamReader, writer: StreamWriter):
        client_id = await self._init_client(reader, writer)
        logger.info(f'Подключился клиент {client_id}')

        while True:
            data = await reader.read(1024)
            if not data:
                break
            # обработка сообщения
            await self._command_process(client_id, data)
        # отключение клиента
        self._client_disconnected(client_id, writer)
        logger.info(f'Клиент отключился {client_id}')

    def _client_disconnected(self, client_id, writer):
        # закрывает stream клиента
        writer.close()
        # удаляем клиента
        self.clients.pop(client_id, None)
        # Устанавливает указатель на индекс последнего сообщения в чате для последующего использования
        self.client_ref[client_id] = len(self.root_chat)

    async def _send_data(self, data, client_id, from_user=None):
        if client_id not in self.clients:
            return
        # получаем stream нужного узера и шлем данные в него
        _, writer = self.clients[client_id]
        # добавляем к сообщению id клиента
        data = f'({from_user}): {data}' if from_user else data
        data += '\n'
        writer.write(data.encode())
        await writer.drain()

    def _save_message(self, client_id, message):
        # сохраняем сообщение в чате только если оно не пустое
        if message != EMPTY_MESSAGE:
            self.root_chat.append(Message(client_id, message, datetime.now()))

    async def _command_process(self, client_id, data):
        mes = data.decode()
        if mes.startswith('/'):
            command = mes[1:].split()[0]
            match command:
                case "pm":
                    await self._send_to_private_chat(client_id, mes)
                case "new":
                    logger.info(f'Клиент {client_id} запросил непрочитанные сообщения.')
                    await self._get_new_mes_for_client(client_id)
                case "file":
                    logger.info(f'Клиент {client_id} отправил файл.')
                    file = await self._read_file(client_id)
                    await self._send_to_root_chat(client_id, '/file')
                    await self._send_to_root_chat(client_id, file.decode())
                case _:
                    await self._send_data(data='Не верная команда!\n', client_id=client_id, from_user='server')
        else:
            self._save_message(client_id, mes)
            await self._send_to_root_chat(client_id, mes)

    async def _read_file(self, client_id):
        # вычитываем файл чанками
        reader, _ = self.clients[client_id]
        data = bytearray()
        while True:
            chunk = await reader.read(1024)
            data += chunk
            if len(chunk) < 1024:
                break

        return data

    async def _send_file_to_root(self, file):
        pass

    async def _send_to_private_chat(self, client_id, mes):
        # парсим id клиента с которым нужно создать приватный чат и сообщение
        mes_list = mes.split()
        pm_client_id = mes_list[1]
        pm_message = ''.join(mes_list[2:]) + '\n'

        # Вернет либо пустой чат, либо чат с прошлыми личными сообщениями двух клиентов
        pm_chats = self.private_chats.setdefault(pm_client_id, [])

        # используем бинарный поиск, для поиска индекса чата
        idx = binary_search([chat['id'] for chat in pm_chats], client_id)
        if idx is not None:
            chat = pm_chats[idx]
            # двигаем указатель на последнее сообщение в чате
            chat['last_read'] = len(chat['mes'])
        else:
            chat = {
                'id': client_id,
                'mes': [],
                'last_read': 0,
            }
            pm_chats.append(chat)
            # когда добавляем новый чат в список, сортируем список, чтобы работал бинарный поиск
            self.private_chats[pm_client_id] = sorted(pm_chats, key=lambda x: x['id'])
        # добавляем сообщение в чат
        chat['mes'].append(pm_message)

        logger.info(f'Клиент {client_id} отправил ЛС для {pm_client_id}.')
        await self._send_data(pm_message, pm_client_id, from_user=client_id)

    async def _send_to_root_chat(self, cid, message):
        if not self._check_mes_limit(cid):
            return

        # Отправляем сообщение всем участникам чата, кроме автора
        for client_id in self.clients:
            if cid != client_id:
                await self._send_data(message, client_id, from_user=cid)

    def _check_mes_limit(self, cid):
        # Проверяем, что не исчерпан лимит на число сообщений
        mes_on_hour = [
            mes
            for mes in self.root_chat
            if mes.login == cid and mes.date >= datetime.now() - timedelta(hours=PERIOD_MES_HOUR)
        ]

        if len(mes_on_hour) > LIMIT_MES_HOUR:
            logger.info(f'Превышен лимит сообщений за час для {cid}')
            return False

        return True

    async def _get_new_mes_for_client(self, client_id):
        # ГЛАВНЫЙ ЧАТ
        # получаем индекс последнего прочитанного сообщения
        if last_read_mes_idx := self.client_ref.get(client_id):
            # отдаем сообщения начиная с непрочитанного
            for mes in self.root_chat[last_read_mes_idx:]:
                await self._send_data(mes.message, client_id, from_user=mes.login)
            # двигаем указатель
            self.client_ref[client_id] = len(self.root_chat)

        # ЛС
        # отправляем все сообщения из приватных чатов клиента начиная с указателя
        chats = self.private_chats.get(client_id, [])
        for chat in chats:
            last_read_mes_idx = chat['last_read'] - 1
            messages = chat['mes']

            for m in messages[last_read_mes_idx:]:
                await self._send_data(m, client_id, from_user=chat['id'])

            chat['last_read'] = len(messages)


async def main(host: str, port: int):
    server = Server()
    srv = await asyncio.start_server(server.client_connected, host, port)
    logger.info(f'Сервер запущен на {host}:{port}')
    async with srv:
        await srv.serve_forever()


if __name__ == '__main__':
    config_logging()
    host, port = get_server_socket()
    try:
        asyncio.run(main(host, port))
    except KeyboardInterrupt:
        pass
