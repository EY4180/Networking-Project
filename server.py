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

PLAYERS_PER_GAME = 2


class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum

    def getName(self):
        return '{}:{}'.format(self.host, self.port)


def rotate(list, n):
    return list[n:] + list[:n]


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


def lobby_thread(queue, lobby):
    while (len(queue) < PLAYERS_PER_GAME):
        continue

    for _ in range(PLAYERS_PER_GAME):
        playerIndex = random.randrange(0, len(queue))
        player = queue.pop(playerIndex)
        lobby.append(player)
        print('\t' + player.getName() +
              " joined the lobby, id " + str(player.idnum))

    return


def game_thread(queue, lobby):
    activePlayers = lobby

    # notify all players of start
    for player in [*queue, *activePlayers]:
        player.connection.send(tiles.MessageGameStart().pack())

    # start game here
    currentPlayer = activePlayers[0]
    live_idnums = []

    # give all players a random hand
    for player in activePlayers:
        live_idnums.append(player.idnum)
        print('\t' + player.getName() +
              " in the game, id " + str(player.idnum))

        for _ in range(tiles.HAND_SIZE):
            tileid = tiles.get_random_tileid()
            msg = tiles.MessageAddTileToHand(tileid).pack()
            player.connection.send(msg)

    # notify players of new turn
    for player in [*queue, *activePlayers]:
        msg = tiles.MessagePlayerTurn(currentPlayer.idnum).pack()
        player.connection.send(msg)

    board = tiles.Board()

    buffer = bytearray()

    # stall program and play game here, stub for now
    while len(activePlayers) > 1:
        chunk = currentPlayer.connection.recv(4096)
        if not chunk:
            print('client {} disconnected'.format(
                currentPlayer.address))
            return

        buffer.extend(chunk)

        while True:
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
                    for player in [*queue, *activePlayers]:
                        player.connection.send(msg.pack())

                    # check for token movement
                    positionupdates, eliminated = board.do_player_movement(
                        live_idnums)

                    for msg in positionupdates:
                        for player in [*queue, *activePlayers]:
                            player.connection.send(msg.pack())

                    if currentPlayer.idnum in eliminated:
                        activePlayers.pop(0)
                        for player in [*queue, *activePlayers]:
                            player.connection.send(
                                tiles.MessagePlayerEliminated(currentPlayer.idnum).pack())

                    # pickup a new tile
                    tileid = tiles.get_random_tileid()
                    currentPlayer.connection.send(
                        tiles.MessageAddTileToHand(tileid).pack())

                    # start next turn
                    activePlayers = rotate(activePlayers, 1)
                    currentPlayer = activePlayers[0]
                    for player in [*queue, *activePlayers]:
                        msg = tiles.MessagePlayerTurn(
                            currentPlayer.idnum).pack()
                        player.connection.send(msg)

            # sent by the player in the second turn, to choose their token's
            # starting path
            elif isinstance(msg, tiles.MessageMoveToken):
                if not board.have_player_position(msg.idnum):
                    if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                        # check for token movement
                        positionupdates, eliminated = board.do_player_movement(
                            live_idnums)

                        for msg in positionupdates:
                            for player in [*queue, *activePlayers]:
                                player.connection.send(msg.pack())

                        if currentPlayer.idnum in eliminated:
                            activePlayers.pop(0)
                            for player in [*queue, *activePlayers]:
                                player.connection.send(
                                    tiles.MessagePlayerEliminated(currentPlayer.idnum).pack())

                        # start next turn
                        activePlayers = rotate(activePlayers, 1)
                        currentPlayer = activePlayers[0]
                        for player in [*queue, *activePlayers]:
                            msg = tiles.MessagePlayerTurn(
                                currentPlayer.idnum).pack()
                            player.connection.send(msg)


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


# gameThread = threading.Thread(target=game_thread)
# gameThread.start()

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

    playerLobby.clear()
    # handle each new connection independently
    # connection, client_address = sock.accept()
    # print('received connection from {}'.format(client_address))
    # client_handler(connection, client_address)
