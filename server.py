# CITS3002 2021 Assignment
#
# This file implements a basic server that allows a single client to play a
# single game with no other participants, and very little error checking.
#
# Any other clients that connect during this time will need to wait for the
# first client's game to complete.
#
# Your task will be to write a new server that adds all connected clients into
# a pool of players. When enough players are available (two or more), the server
# will create a game with a random sample of those players (no more than
# tiles.PLAYER_LIMIT players will be in any one game). Players will take turns
# in an order determined by the server, continuing until the game is finished
# (there are less than two players remaining). When the game is finished, if
# there are enough players available the server will start a new game with a
# new selection of clients.

import socket
import sys
import tiles
import threading
import random
import time
import select
from os import system, name

PLAYERS_PER_GAME = 4

playerGame = []

class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum
        self.moveCount = 0

    def __eq__(self, other):
        return self.idnum == other.idnum

    def getName(self):
        return '{}:{}'.format(self.host, self.port)


def boradcastCurrentPlayer(clients, currentPlayer):
    for client in clients:
        msg = tiles.MessagePlayerTurn(currentPlayer.idnum).pack()
        client.connection.send(msg)


def boradcastPlayerEliminated(clients, player):
    for client in clients:
        msg = tiles.MessagePlayerEliminated(player.idnum).pack()
        client.connection.send(msg)


def boradcastPlayerLeave(clients, player):
    for client in clients:
        msg = tiles.MessagePlayerLeft(player.idnum).pack()
        client.connection.send(msg)


def boradcastGameStart(clients):
    for client in clients:
        msg = tiles.MessageGameStart().pack()
        client.connection.send(msg)


def boradcastPositionUpdates(clients, updates):
    for client in clients:
        for update in updates:
            client.connection.send(update.pack())


def boradcastCountdown(clients):
    for client in clients:
        client.connection.send(tiles.MessageCountdown().pack())


def logging(queue: list, lobby: list):
    while True:
        # for windows
        if name == 'nt':
            _ = system('cls')

        # for mac and linux(here, os.name is 'posix')
        else:
            _ = system('clear')

        print("Connected Users")
        for client in [*lobby, *queue]:
            print("\t" + client.getName())

        print("Lobby [{}/{}]".format(len(lobby), tiles.PLAYER_LIMIT))
        for client in lobby:
            print("\t" + client.getName())

        print("Queue [{}]".format(len(queue)))
        for client in queue:
            print("\t" + client.getName())

        time.sleep(1)


def update_status(queue: list, lobby: list):
    global playerGame

    while True:
        activeSockets = []
        activeClients = [*queue, *lobby]
        for client in activeClients:
            activeSockets.append(client.connection)

        try:
            ready, _, _ = select.select(activeSockets, [], [], 0.1)
            for clientConnection in ready:
                message = clientConnection.recv(1024)
                if not message:
                    client = activeClients[activeSockets.index(
                        clientConnection)]
                    if client in lobby:
                        lobby.remove(client)
                        # key issue here is that you cant broadcast this unless the player has played a tile, so if the user exits on entry you are screwed
                        if client in playerGame:
                            boradcastPlayerEliminated([*queue, *lobby], client)
                    elif client in queue:
                        queue.remove(client)

                    boradcastPlayerLeave([*queue, *lobby], client)
        except:
            continue


def update_queue(queue, lobby):
    # constantly check for new clients
    idnum = 0
    while True:
        # handle new connection
        connection, client_address = sock.accept()

        # add player to queue
        newPlayer = Player(connection, client_address, idnum)
        idnum += 1

        # send messages
        connection.send(tiles.MessageWelcome(newPlayer.idnum).pack())

        # make sure all clients know other clients
        for player in [*queue, *lobby]:
            player.connection.send(tiles.MessagePlayerJoined(
                newPlayer.getName(), newPlayer.idnum).pack())

            newPlayer.connection.send(tiles.MessagePlayerJoined(
                player.getName(), player.idnum).pack())

        queue.append(newPlayer)


def lobby_thread(queue: list, lobby: list):
    while (len(queue) < 2):
        continue

    boradcastCountdown([*queue, *lobby])
    lobbySize = min([len(queue), tiles.PLAYER_LIMIT])

    for _ in range(lobbySize):
        playerIndex = random.randrange(0, len(queue))
        player = queue.pop(playerIndex)
        lobby.append(player)
    return


def get_live_idnums(lobby: list):
    live_idnums = []
    for client in lobby:
        live_idnums.append(client.idnum)

    return live_idnums


def game_thread(queue: list, lobby: list):
    global playerGame

    # notify all players of start
    for player in [*queue, *lobby]:
        player.connection.send(tiles.MessageGameStart().pack())

    # give all players a random hand
    for player in lobby:
        for _ in range(tiles.HAND_SIZE):
            tileid = tiles.get_random_tileid()
            msg = tiles.MessageAddTileToHand(tileid).pack()
            player.connection.send(msg)

    board = tiles.Board()

    buffer = bytearray()

    currentPlayer = lobby[0]
    boradcastCurrentPlayer([*queue, *lobby], currentPlayer)
    # stall program and play game here, stub for now
    while True:
        # start next turn
        if currentPlayer != lobby[0]:
            currentPlayer = lobby[0]
            boradcastCurrentPlayer([*queue, *lobby], currentPlayer)

        ready, _, _ = select.select([currentPlayer.connection], [], [], 5)
        for readyConnection in ready:
            chunk = currentPlayer.connection.recv(4096)
            if chunk:
                buffer.extend(chunk)

                while True:
                    live_idnums = get_live_idnums(lobby)

                    msg, consumed = tiles.read_message_from_bytearray(buffer)
                    if not consumed:
                        break

                    buffer = buffer[consumed:]

                    # sent by the player to put a tile onto the board (in all turns except
                    # their second)
                    if isinstance(msg, tiles.MessagePlaceTile):
                        if board.set_tile(msg.x, msg.y, msg.tileid, msg.rotation, msg.idnum):
                            # notify client that placement was successful
                            for player in [*queue, *lobby]:
                                player.connection.send(msg.pack())

                            # check for token movement
                            positionupdates, eliminated = board.do_player_movement(
                                live_idnums)

                            boradcastPositionUpdates(
                                [*queue, *lobby], positionupdates)

                            lobby.append(lobby.pop(0))
                            if currentPlayer not in playerGame:
                                playerGame.append(currentPlayer)

                            if currentPlayer.idnum in eliminated:
                                boradcastPlayerEliminated(
                                    [*queue, *lobby], currentPlayer)
                                queue.append(currentPlayer)
                                lobby.remove(currentPlayer)

                            # pickup a new tile
                            tileid = tiles.get_random_tileid()
                            currentPlayer.connection.send(
                                tiles.MessageAddTileToHand(tileid).pack())

                    # sent by the player in the second turn, to choose their token's
                    # starting path
                    elif isinstance(msg, tiles.MessageMoveToken):
                        if not board.have_player_position(msg.idnum):
                            if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                                # check for token movement
                                positionupdates, eliminated = board.do_player_movement(
                                    live_idnums)

                                boradcastPositionUpdates(
                                    [*queue, *lobby], positionupdates)

                                lobby.append(lobby.pop(0))
                            if currentPlayer not in playerGame:
                                playerGame.append(currentPlayer)

                                if currentPlayer.idnum in eliminated:
                                    boradcastPlayerEliminated(
                                        [*queue, *lobby], currentPlayer)
                                    queue.append(currentPlayer)
                                    lobby.remove(currentPlayer)
        if (len(lobby) == 1):
            queue.extend(lobby)
            lobby.clear()
            playerGame.clear()
            return


# create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# listen on all network interfaces
server_address = ('', 30020)
sock.bind(server_address)

sock.listen(5)

playerQueue = []
playerLobby = []

# constantly handle incomming connections
connectionThread = threading.Thread(
    target=update_queue, args=(playerQueue, playerLobby))
connectionThread.start()

# evaluate health of connections
ststusThread = threading.Thread(
    target=update_status, args=(playerQueue, playerLobby))
ststusThread.start()

loggingThread = threading.Thread(
    target=logging, args=(playerQueue, playerLobby))
loggingThread.start()

while True:
    # wait for players to fill the lobby
    # time.sleep(5)

    lobbyFormationThread = threading.Thread(
        target=lobby_thread, args=(playerQueue, playerLobby))
    lobbyFormationThread.start()
    lobbyFormationThread.join()

    # start game
    gameThread = threading.Thread(
        target=game_thread, args=(playerQueue, playerLobby))
    gameThread.start()
    gameThread.join()

    time.sleep(5)
    # handle each new connection independently
    # connection, client_address = sock.accept()
    # print('received connection from {}'.format(client_address))
    # client_handler(connection, client_address)
