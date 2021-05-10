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
from threading import Thread
import random
import time
import select
from os import system, name


class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum
        self.message = None
        self.hand = []

    def __eq__(self, other):
        return self.idnum == other.idnum

    def getName(self):
        return '{}:{}'.format(self.host, self.port)


def boradcastCurrentPlayer(clients, currentPlayer):
    global updateStack
    msg = tiles.MessagePlayerTurn(currentPlayer.idnum).pack()
    updateStack.append(msg)
    for client in clients:
        client.message = None
        client.connection.send(msg)


def boradcastPlayerEliminated(clients, player):
    global updateStack
    msg = tiles.MessagePlayerEliminated(player.idnum).pack()
    updateStack.append(msg)

    for client in clients:
        client.connection.send(msg)


def boradcastPlayerLeave(clients, player):
    for client in clients:
        msg = tiles.MessagePlayerLeft(player.idnum).pack()
        client.connection.send(msg)


def boradcastGameStart(clients):
    global updateStack
    msg = tiles.MessageGameStart().pack()
    updateStack.append(msg)

    for client in clients:
        client.connection.send(msg)


def boradcastPositionUpdates(clients, updates):
    global updateStack

    for update in updates:
        updateStack.append(update.pack())
        for client in clients:
            client.connection.send(update.pack())


def broadcastPlaceSuccessful(clients, msg):
    global updateStack
    updateStack.append(msg)

    for client in clients:
        client.connection.send(msg)


def boradcastCountdown(clients):
    msg = tiles.MessageCountdown().pack()
    for client in clients:
        client.connection.send(msg)


def broadcastUpdates(lobby, queue, board, current):
    live_idnums = [client.idnum for client in lobby]
    positionupdates, eliminated = board.do_player_movement(live_idnums)

    boradcastPositionUpdates(lobby + queue, positionupdates)

    # get eliminated clients
    eliminatedClients = [
        client for client in lobby if client.idnum in eliminated]

    # change players turn
    lobby.append(lobby.pop(0))

    # eliminated player exits game and returns to queue
    for client in eliminatedClients:
        boradcastPlayerEliminated(lobby + queue, client)
        queue.append(client)
        lobby.remove(client)


def update_status(queue: list, lobby: list, server, updateStack: list):
    while True:
        activeSockets = [server]
        for client in lobby + queue:
            activeSockets.append(client.connection)

        ready, _, _ = select.select(activeSockets, [], [])

        for clientConnection in ready:
            if clientConnection is server:
                # handle new connection
                connection, client_address = server.accept()

                # find avaliable id numbers
                usedID = {client.idnum for client in lobby + queue}
                unusedID = set(range(tiles.IDNUM_LIMIT)) - usedID

                # add player to queue
                idnum = unusedID.pop()
                newPlayer = Player(connection, client_address, idnum)

                # send messages
                connection.send(tiles.MessageWelcome(
                    newPlayer.idnum).pack())

                # make sure all clients know other clients
                for player in lobby + queue:
                    player.connection.send(tiles.MessagePlayerJoined(
                        newPlayer.getName(), newPlayer.idnum).pack())

                    newPlayer.connection.send(tiles.MessagePlayerJoined(
                        player.getName(), player.idnum).pack())

                # send cumilative updates to joining client
                for msg in updateStack:
                    newPlayer.connection.send(msg)

                queue.append(newPlayer)
            else:
                message = clientConnection.recv(4096)

                for client in lobby:
                    if client.connection is clientConnection:
                        client.message = message
                        # player in game disconnected
                        if not message:
                            lobby.remove(client)
                            boradcastPlayerEliminated(lobby + queue, client)
                            boradcastPlayerLeave(lobby + queue, client)
                        break

                for client in queue:
                    if client.connection is clientConnection:
                        client.message = message
                        # player in queue disconnected
                        if not message:
                            queue.remove(client)
                            boradcastPlayerLeave(lobby + queue, client)
                        break


def random_move(currentPlayer: Player, board: tiles.Board):
    validCoordinates = []
    chunk = None
    for x in range(tiles.BOARD_WIDTH):
        for y in range(tiles.BOARD_HEIGHT):
            validCoordinates.append((x, y))

    if board.have_player_position(currentPlayer.idnum):
        # player needs to place a tile
        playerX, playerY, _ = board.get_player_position(currentPlayer.idnum)
        rotation = random.randrange(0, 4)
        tileid = random.choice(currentPlayer.hand)
        chunk = tiles.MessagePlaceTile(
            currentPlayer.idnum, tileid, rotation, playerX, playerY)
    else:
        for x, y in validCoordinates:
            _, _, ownerID = board.get_tile(x, y)
            if ownerID == currentPlayer.idnum:
                # choose a starting location (move 2)
                avaliablePositions = []
                if x == 0:
                    avaliablePositions.extend([7, 6])
                if y == 0:
                    avaliablePositions.extend([5, 4])
                if x == board.width - 1:
                    avaliablePositions.extend([3, 2])
                if y == board.height - 1:
                    avaliablePositions.extend([1, 0])

                position = random.choice(avaliablePositions)
                chunk = tiles.MessageMoveToken(currentPlayer.idnum, x, y, position)
                break
        else:
            # place first tile (move 1)
            edgeCoordinates = []
            for x, y in validCoordinates:
                edgeX = x in [0, tiles.BOARD_WIDTH - 1]
                edgeY = y in [0, tiles.BOARD_HEIGHT - 1]

                index = board.tile_index(x, y)
                if (edgeX or edgeY) and not board.tileids[index]:
                    edgeCoordinates.append((x, y))

            x, y = random.choice(edgeCoordinates)
            tileid = random.choice(currentPlayer.hand)
            rotation = random.randrange(0, 4)

            chunk = tiles.MessagePlaceTile(
                currentPlayer.idnum, tileid, rotation, x, y)

    return chunk.pack()


def game_thread(queue: list, lobby: list, updateStack: list):
    while True:
        # move players in lobby to queue and clear lobby
        queue.extend(playerLobby)
        lobby.clear()
        updateStack.clear()

        while (len(queue) < 2):
            continue

        boradcastCountdown(lobby + queue)
        lobbySize = min([len(queue), tiles.PLAYER_LIMIT])

        while len(lobby) < lobbySize:
            player = random.choice(queue)
            queue.remove(player)
            lobby.append(player)

        # notify all players of start
        boradcastGameStart(lobby + queue)

        # give all players a random hand
        for player in lobby:
            boradcastCurrentPlayer(lobby + queue, player)
            player.hand.clear()
            for _ in range(tiles.HAND_SIZE):
                tileid = tiles.get_random_tileid()
                msg = tiles.MessageAddTileToHand(tileid).pack()
                player.connection.send(msg)
                player.hand.append(tileid)

        # start main game loop
        board = tiles.Board()
        currentPlayer = None
        startTime = time.time()

        while len(lobby) > 1:
            # start next turn
            if currentPlayer is not lobby[0]:
                currentPlayer = lobby[0]
                boradcastCurrentPlayer(lobby + queue, currentPlayer)
                startTime = time.time()

            try:
                chunk = currentPlayer.message
                # replace player message with random move if overtime
                if time.time() - startTime > 0.3:
                    chunk = random_move(currentPlayer, board)

                # check if this message is populated
                if not chunk:
                    raise Exception("No Message or Disconnect")

                buffer = bytearray()
                buffer.extend(chunk)
                msg, consumed = tiles.read_message_from_bytearray(buffer)

                # no idea how this exception could happen but included because
                # original code had it
                if not consumed:
                    raise Exception("Message Not Read Into Buffer")

                buffer = buffer[consumed:]

                placingTile = isinstance(msg, tiles.MessagePlaceTile)
                selectingToken = isinstance(msg, tiles.MessageMoveToken)

                if placingTile:
                    if board.set_tile(msg.x, msg.y, msg.tileid, msg.rotation, msg.idnum):
                        index = board.tile_index(msg.x, msg.y)

                        # notify client that placement was successful
                        broadcastPlaceSuccessful(lobby + queue, msg.pack())

                        # pickup a new tile
                        tileid = tiles.get_random_tileid()
                        tilemsg = tiles.MessageAddTileToHand(tileid).pack()
                        currentPlayer.connection.send(tilemsg)

                        currentPlayer.hand.append(tileid)
                        currentPlayer.hand.remove(msg.tileid)

                        broadcastUpdates(lobby, queue, board, currentPlayer)
                elif selectingToken:
                    if not board.have_player_position(msg.idnum):
                        if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                            broadcastUpdates(lobby, queue, board, currentPlayer)
            except:
                continue


# create a TCP/IP socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# listen on all network interfaces
server_address = ('', 30020)
server.bind(server_address)

server.listen(5)

updateStack = []
playerQueue = []
playerLobby = []

# constantly handle incomming connections
statusThread = Thread(target=update_status, args=(
    playerQueue, playerLobby, server, updateStack))
statusThread.start()
# start game
gameThread = Thread(target=game_thread, args=(
    playerQueue, playerLobby, updateStack))
gameThread.start()
while True:
    continue
