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
import collections
from os import system, name

PLAYERS_PER_GAME = 4
originalOrder = []
updateStack = []

class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum
        self.messages = collections.deque()
        self.hand = []

    def __eq__(self, other):
        return self.idnum == other.idnum

    def getName(self):
        return '{}:{}'.format(self.host, self.port)


def boradcastCurrentPlayer(clients, currentPlayer):
    msg = tiles.MessagePlayerTurn(currentPlayer.idnum).pack()
    for client in clients:
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
    for client in clients:
        msg = tiles.MessageGameStart().pack()
        client.connection.send(msg)


def boradcastPositionUpdates(clients, updates):
    global updateStack
    for update in updates:
        updateStack.append(update.pack())
        for client in clients:
            client.connection.send(update.pack())

def broadcastPlaceSuccessful(clients, msg):
    global updateStack
    updateStack.append(msg.pack())

    for client in clients:
        client.connection.send(msg.pack())

def boradcastCountdown(clients):
    for client in clients:
        client.connection.send(tiles.MessageCountdown().pack())

def broadcastUpdates(lobby, queue, board, current):
    live_idnums = [client.idnum for client in lobby]
    positionupdates, eliminated = board.do_player_movement(
    live_idnums)

    boradcastPositionUpdates(queue + lobby, positionupdates)

    lobby.append(lobby.pop(0))

    if current.idnum in eliminated:
        boradcastPlayerEliminated(queue + lobby, current)
        queue.append(current)
        lobby.remove(current)

def logging(queue: list, lobby: list):
    while True:
        # for windows
        if name == 'nt':
            _ = system('cls')

        # for mac and linux(here, os.name is 'posix')
        else:
            _ = system('clear')

        print("Connected Users [{}]".format(len(lobby + queue)))
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
    while True:
        activeSockets = []
        for client in [*queue, *lobby]:
            activeSockets.append(client.connection)

        try:
            ready, _, _ = select.select(activeSockets, [], [], 0)

            for clientConnection in ready:
                message = clientConnection.recv(4096)

                for client in lobby:
                    if client.connection == clientConnection:
                        client.messages.appendleft(message)
                        if not message:
                            lobby.remove(client)
                            boradcastPlayerEliminated([*queue, *lobby], client)
                            boradcastPlayerLeave([*queue, *lobby], client)
                        break

                for client in queue:
                    if client.connection == clientConnection:
                        client.messages.appendleft(message)
                        if not message:
                            queue.remove(client)
                            boradcastPlayerLeave([*queue, *lobby], client)
                        break
        except:
            continue


def update_queue(queue, lobby, sock):
    global originalOrder
    global updateStack
    # constantly check for new clients
    while True:
        # handle new connection
        connection, client_address = sock.accept()

        # find avaliable id numbers
        usedID = {client.idnum for client in lobby + queue}
        unusedID = set(range(tiles.IDNUM_LIMIT)) - usedID

        # add player to queue
        idnum = unusedID.pop()
        newPlayer = Player(connection, client_address, idnum)

        # send messages
        connection.send(tiles.MessageWelcome(newPlayer.idnum).pack())

        # make sure all clients know other clients
        for player in queue + lobby:
            player.connection.send(tiles.MessagePlayerJoined(
                newPlayer.getName(), newPlayer.idnum).pack())

            newPlayer.connection.send(tiles.MessagePlayerJoined(
                player.getName(), player.idnum).pack())

        queue.append(newPlayer)

        # send cumilative updates to joining client
        if len(lobby) != 0:
            boradcastGameStart([newPlayer])
            # notify client of all players
            for client in originalOrder:
                boradcastCurrentPlayer([newPlayer], client)

            # notify of current player
            boradcastCurrentPlayer([newPlayer], lobby[0])

            # notify of all board updates
            for msg in updateStack:
                newPlayer.connection.send(msg)

def lobby_thread(queue: list, lobby: list):
    global updateStack
    global originalOrder
    originalOrder.clear()
    updateStack.clear()

    while (len(queue) < 2):
        continue

    boradcastCountdown(queue + lobby)
    time.sleep(2)

    lobbySize = min([len(queue), tiles.PLAYER_LIMIT])

    while len(lobby) < lobbySize:
        playerIndex = random.randrange(0, len(queue))
        player = queue.pop(playerIndex)
        lobby.append(player)
    
    originalOrder.extend(lobby)
    return

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
        tileid = currentPlayer.hand[random.randrange(0, len(currentPlayer.hand))]
        chunk = tiles.MessagePlaceTile(currentPlayer.idnum, tileid, rotation, playerX, playerY)
    else:
        for x, y in validCoordinates:
            _, _, ownerID = board.get_tile(x, y)
            if ownerID == currentPlayer.idnum:
                # choose a starting location (move 2)
                avaliablePositions = []

                if y == tiles.BOARD_HEIGHT - 1:
                    avaliablePositions.extend([0, 1])
                if x == tiles.BOARD_WIDTH - 1:
                    avaliablePositions.extend([2, 3])
                if y == 0:
                    avaliablePositions.extend([4, 5])
                if x == 0:
                    avaliablePositions.extend([6, 7])

                position = avaliablePositions[random.randrange(0, len(avaliablePositions))]
                chunk = tiles.MessageMoveToken(currentPlayer.idnum, x, y, position)
                break
        else:
            # place first tile (move 1)
            edgeCoordinates = []
            for x, y in validCoordinates:
                edgeX = x in [0, tiles.BOARD_WIDTH - 1] 
                edgeY = y in [0, tiles.BOARD_HEIGHT - 1] 

                tile, _, _ = board.get_tile(x, y)
                if (edgeX or edgeY) and not tile:
                    edgeCoordinates.append((x, y))
         
            x, y = edgeCoordinates[random.randrange(0, len(edgeCoordinates))]
            tileid = currentPlayer.hand[random.randrange(0, len(currentPlayer.hand))]
            rotation = random.randrange(0, 4)

            chunk = tiles.MessagePlaceTile(currentPlayer.idnum, tileid, rotation, x, y)
    return chunk.pack()
            
def game_thread(queue: list, lobby: list):
    # notify all players of start
    boradcastGameStart(queue + lobby)        

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
    startTime = None
    while len(lobby) != 1:
        # start next turn
        if currentPlayer is not lobby[0]:
            currentPlayer = lobby[0]
            currentPlayer.messages.clear()
            boradcastCurrentPlayer(queue + lobby, currentPlayer)
            startTime = time.time()
            
        try:
            chunk = None
            if abs(time.time() - startTime) > 10:
                chunk = random_move(currentPlayer, board)
            else:
                chunk = currentPlayer.messages.popleft()
                                         
            # this exception is not expected to happen
            if not chunk:
                raise Exception("Client Disconnected")

            buffer = bytearray()
            buffer.extend(chunk)
            msg, consumed = tiles.read_message_from_bytearray(buffer)
            
            # no idea how this exception could happen but included because 
            # original code had it
            if not consumed:
                raise Exception("Unable To Read Message")

            buffer = buffer[consumed:]
            
            placingTile = isinstance(msg, tiles.MessagePlaceTile)
            selectingToken = isinstance(msg, tiles.MessageMoveToken)
            
            if placingTile:
                if board.set_tile(msg.x, msg.y, msg.tileid, msg.rotation, msg.idnum):
                    # notify client that placement was successful
                    broadcastPlaceSuccessful(queue + lobby, msg)
                    broadcastUpdates(lobby, queue, board, currentPlayer)

                    # pickup a new tile
                    tileid = tiles.get_random_tileid()
                    tilemsg = tiles.MessageAddTileToHand(tileid).pack()
                    currentPlayer.connection.send(tilemsg)
                    
                    currentPlayer.hand.append(tileid)
                    currentPlayer.hand.remove(msg.tileid)

            elif selectingToken:
                if not board.have_player_position(msg.idnum):
                    if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                        broadcastUpdates(lobby, queue, board, currentPlayer)
        except:
            continue

    queue.extend(lobby)
    lobby.clear()


# create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# listen on all network interfaces
server_address = ('', 30020)
sock.bind(server_address)

sock.listen(5)

playerQueue = []
playerLobby = []

# constantly handle incomming connections
connectionThread = Thread(target=update_queue, args=(playerQueue, playerLobby, sock))
connectionThread.start()

# evaluate health of connections
statusThread = Thread(target=update_status, args=(playerQueue, playerLobby))
statusThread.start()

loggingThread = Thread(target=logging, args=(playerQueue, playerLobby))
loggingThread.start()

while True:
    # wait for players to fill the lobby
    lobbyFormationThread = Thread(
        target=lobby_thread, args=(playerQueue, playerLobby))
    lobbyFormationThread.start()
    lobbyFormationThread.join()

    # start game
    gameThread = Thread(target=game_thread, args=(playerQueue, playerLobby))
    gameThread.start()
    gameThread.join()