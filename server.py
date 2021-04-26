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

PLAYERS_PER_GAME = 2


class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum

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


def rotate(list, n):
    return list[n:] + list[:n]


'''
    Manage the health of everyone connected to the server. If I have any sanity
    left, I would have implemented a lock or memory barrier when checking the
    connection status to stop any transmissions going to any players that have
    disconnected
'''


def update_status(queue: list, lobby: list, socket):
    while True:
        activeSockets = []
        activeClients = [*queue, *lobby]
        for client in activeClients:
            activeSockets.append(client.connection)

        try:
            ready, _, _ = select.select(activeSockets, [], [], 0.1)
            for clientConnection in ready:
                message = clientConnection.recv(1024)
                client = activeClients[activeSockets.index(clientConnection)]
                if not message:
                    print('client {} disconnected'.format(client.getName()))
                    if client in lobby:
                        lobby.remove(client)
                    elif client in queue:
                        queue.remove(client)

                    boradcastPlayerEliminated([*queue, *lobby], client)
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
        print('received connection from {}'.format(client_address))
        connection.send(tiles.MessageWelcome(newPlayer.idnum).pack())

        # make sure all clients know other clients
        for player in [*queue, *lobby]:
            player.connection.send(tiles.MessagePlayerJoined(
                newPlayer.getName(), newPlayer.idnum).pack())

            newPlayer.connection.send(tiles.MessagePlayerJoined(
                player.getName(), player.idnum).pack())

        queue.append(newPlayer)


def lobby_thread(queue, lobby:list):
    while (len(queue) < PLAYERS_PER_GAME):
        continue

    # can we start a game with less than four players ?
    # lobbySize = tiles.PLAYER_LIMIT
    queue.extend(lobby)
    lobby.clear()

    for _ in range(PLAYERS_PER_GAME):
        playerIndex = random.randrange(0, len(queue))
        player = queue.pop(playerIndex)
        lobby.append(player)
        print('\t' + player.getName() +
              " joined the lobby, id " + str(player.idnum) + " " + str(len(queue)))

    return


def get_live_idnums(lobby: list):
    live_idnums = []
    for client in lobby:
        live_idnums.append(client.idnum)

    return live_idnums


def game_thread(queue: list, lobby: list):
    # notify all players of start
    for player in [*queue, *lobby]:
        player.connection.send(tiles.MessageGameStart().pack())

    # start game here
    currentPlayer = lobby[0]

    # give all players a random hand
    for player in lobby:
        print('\t' + player.getName() +
              " in the game, id " + str(player.idnum))

        for _ in range(tiles.HAND_SIZE):
            tileid = tiles.get_random_tileid()
            msg = tiles.MessageAddTileToHand(tileid).pack()
            player.connection.send(msg)

    # notify players of new turn
    boradcastCurrentPlayer([*queue, *lobby], currentPlayer)

    board = tiles.Board()

    buffer = bytearray()

    # stall program and play game here, stub for now
    stop = False
    while True:
        currentPlayer = lobby[0]
        chunk = lobby[0].connection.recv(4096)
        if chunk:
            buffer.extend(chunk)

            while (currentPlayer in lobby):
                live_idnums = get_live_idnums(lobby)

                msg, consumed = tiles.read_message_from_bytearray(buffer)
                if not consumed:
                    break

                buffer = buffer[consumed:]

                print('received message {}'.format(msg))

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

                        boradcastPositionUpdates([*queue, *lobby], positionupdates)

                        if currentPlayer.idnum in eliminated:
                            boradcastPlayerEliminated([*queue, *lobby], currentPlayer)
                            lobby.remove(currentPlayer)
                            queue.append(currentPlayer)
                        
                        # pickup a new tile
                        tileid = tiles.get_random_tileid()
                        currentPlayer.connection.send(
                            tiles.MessageAddTileToHand(tileid).pack())

                        # start next turn
                        lobby = rotate(lobby, 1)
                        currentPlayer = lobby[0]
                        boradcastCurrentPlayer([*queue, *lobby], currentPlayer)

                # sent by the player in the second turn, to choose their token's
                # starting path
                elif isinstance(msg, tiles.MessageMoveToken):
                    if not board.have_player_position(msg.idnum):
                        if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                            # check for token movement
                            positionupdates, eliminated = board.do_player_movement(
                                live_idnums)

                            boradcastPositionUpdates([*queue, *lobby], positionupdates)

                            if currentPlayer.idnum in eliminated:
                                boradcastPlayerEliminated([*queue, *lobby], currentPlayer)
                                lobby.remove(currentPlayer)
                                queue.append(currentPlayer)


                            # start next turn
                            lobby = rotate(lobby, 1)
                            currentPlayer = lobby[0]
                            boradcastCurrentPlayer([*queue, *lobby], currentPlayer)

# create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# listen on all network interfaces
server_address = ('', 30020)
sock.bind(server_address)

print('listening on {}'.format(sock.getsockname()))

sock.listen(5)

playerQueue = []
playerLobby = []

# constantly handle incomming connections
connectionThread = threading.Thread(
    target=update_queue, args=(playerQueue, playerLobby))
connectionThread.start()

# evaluate health of connections
ststusThread = threading.Thread(
    target=update_status, args=(playerQueue, playerLobby, socket))
ststusThread.start()

while True:
    # wait for lobby to be formed
    lobbyFormationThread = threading.Thread(
        target=lobby_thread, args=(playerQueue, playerLobby))
    lobbyFormationThread.start()
    lobbyFormationThread.join()

    # start game and wait for completion
    gameThread = threading.Thread(
        target=game_thread, args=(playerQueue, playerLobby))
    gameThread.start()
    gameThread.join()

    time.sleep(5)
    # handle each new connection independently
    # connection, client_address = sock.accept()
    # print('received connection from {}'.format(client_address))
    # client_handler(connection, client_address)
