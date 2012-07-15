from array import array

from pychess.Utils.const import *
from pychess.Utils.repr import reprColor
from ldata import *
from attack import isAttacked
from bitboard import *
from PolyglotHash import *
from threading import RLock
from copy import deepcopy

################################################################################
# FEN                                                                          #
################################################################################

# This will cause applyFen to raise an exception, if halfmove clock and fullmove
# number is not specified
STRICT_FEN = False

# Final positions of castled kings and rooks
fin_kings = ((C1,G1),(C8,G8))
fin_rooks = ((D1,F1),(D8,F8))

################################################################################
# LBoard                                                                       #
################################################################################

class LBoard:
    def __init__ (self, variant):
        self.variant = variant
        self._reset()
    
    def _reset (self):
        """ Set board to empty on Black's turn (which Polyglot-hashes to 0) """
        self.blocker = createBoard(0)
        
        self.friends = [createBoard(0)]*2
        self.kings = [-1]*2
        self.boards = [[createBoard(0)]*7 for i in range(2)]
        
        self.enpassant = None
        self.color = BLACK
        self.castling = 0
        self.hasCastled = [False, False]
        self.fifty = 0
        self.plyCount = 0
        
        self.checked = None
        self.opchecked = None
        
        self.arBoard = array("B", [0]*64)
        
        self.hash = 0
        self.pawnhash = 0
        
        ########################################################################
        #  The format of history is a list of tuples of the following fields   #
        #  move:       The move that was applied to get the position           #
        #  tpiece:     The piece the move captured, == EMPTY for normal moves  #
        #  enpassant:  cord which can be captured by enpassant or None         #
        #  castling:   The castling availability in the position               #
        #  hash:       The hash of the position                                #
        #  fifty:      A counter for the fifty moves rule                      #
        ########################################################################
        self.history = []

        # initial cords of rooks and kings for castling in Chess960
        if self.variant == FISCHERRANDOMCHESS:
            self.ini_kings = [None, None]
            self.ini_rooks = [[None, None], [None, None]]
        else:
            self.ini_kings = [E1, E8]
            self.ini_rooks = [[A1, H1], [A8, H8]]
    
    @property
    def lastMove (self):
        return self.history[-1][0]

    def repetitionCount (self, drawThreshold=3):
        rc = 1
        for ply in xrange(4, 1+min(len(self.history), self.fifty), 2):
            if self.history[-ply][4] == self.hash:
                rc += 1
                if rc >= drawThreshold: break
        return rc

    def applyFen (self, fenstr):
        """ Applies the fenstring to the board.
            If the string is not properly
            written a SyntaxError will be raised, having its message ending in
            Pos(%d) specifying the string index of the problem.
            if an error is found, no changes will be made to the board. """
        
        # Get information
        
        parts = fenstr.split()
        
        if len(parts) > 6:
            raise SyntaxError, "Can't have more than 6 fields in fenstr. "+ \
                               "Pos(%d)" % fenstr.find(parts[6])
        
        if STRICT_FEN and len(parts) != 6:
            raise SyntaxError, "Needs 6 fields in fenstr. Pos(%d)" % len(fenstr)
        
        elif len(parts) < 4:
            raise SyntaxError, "Needs at least 6 fields in fenstr. Pos(%d)" % \
                                                                     len(fenstr)
        
        elif len(parts) >= 6:
            pieceChrs, colChr, castChr, epChr, fiftyChr, moveNoChr = parts[:6]
        
        elif len(parts) == 5:
            pieceChrs, colChr, castChr, epChr, fiftyChr = parts
            moveNoChr = "1"
        
        else:
            pieceChrs, colChr, castChr, epChr = parts
            fiftyChr = "0"
            moveNoChr = "1"
        
        # Try to validate some information
        # TODO: This should be expanded and perhaps moved
        
        slashes = len([c for c in pieceChrs if c == "/"])
        if slashes != 7:
            raise SyntaxError, "Needs 7 slashes in piece placement field. "+ \
                               "Pos(%d)" % fenstr.rfind("/")
        
        if not colChr.lower() in ("w", "b"):
            raise SyntaxError, "Active color field must be one of w or b. "+ \
                               "Pos(%d)" % fenstr.find(len(pieceChrs), colChr)
        
        if epChr != "-" and not epChr in cordDic:
            raise SyntaxError, ("En passant cord %s is not legal. "+ \
                                "Pos(%d) - %s") % (epChr, fenstr.rfind(epChr), \
                                 fenstr)
        
        if (not 'k' in pieceChrs) or (not 'K' in pieceChrs):
            raise SyntaxError, "FEN needs at least 'k' and 'K' in piece placement field."

        # Reset this board
        
        self._reset()
        
        # Parse piece placement field
        
        for r, rank in enumerate(pieceChrs.split("/")):
            cord = (7-r)*8
            for char in rank:
                if char.isdigit():
                    cord += int(char)
                else:
                    color = char.islower() and BLACK or WHITE
                    piece = reprSign.index(char.upper())
                    self._addPiece(cord, piece, color)
                    cord += 1

            if self.variant == FISCHERRANDOMCHESS:
                # Save ranks fo find outermost rooks
                # if KkQq was used in castling rights
                if r == 0:
                    rank8 = rank
                elif r == 7:
                    rank1 = rank

        # Parse active color field
        
        if colChr.lower() == "w":
            self.setColor (WHITE)
        else: self.setColor (BLACK)
        
        # Parse castling availability

        castling = 0
        for char in castChr:
            if self.variant == FISCHERRANDOMCHESS:
                if char in reprFile:
                    if char < reprCord[self.kings[BLACK]][0]:
                        castling |= B_OOO
                        self.ini_rooks[1][0] = reprFile.index(char) + 56
                    else:
                        castling |= B_OO
                        self.ini_rooks[1][1] = reprFile.index(char) + 56
                    self.ini_kings[BLACK] = self.kings[BLACK]
                elif char in [c.upper() for c in reprFile]:
                    if char < reprCord[self.kings[WHITE]][0].upper():
                        castling |= W_OOO
                        self.ini_rooks[0][0] = reprFile.index(char.lower())
                    else:
                        castling |= W_OO
                        self.ini_rooks[0][1] = reprFile.index(char.lower())
                    self.ini_kings[WHITE] = self.kings[WHITE]
                elif char == "K":
                    castling |= W_OO
                    self.ini_rooks[0][1] = rank1.rfind('R')
                    self.ini_kings[WHITE] = self.kings[WHITE]
                elif char == "Q":
                    castling |= W_OOO
                    self.ini_rooks[0][0] = rank1.find('R')
                    self.ini_kings[WHITE] = self.kings[WHITE]
                elif char == "k":
                    castling |= B_OO
                    self.ini_rooks[1][1] = rank8.rfind('r') + 56
                    self.ini_kings[BLACK] = self.kings[BLACK]
                elif char == "q":
                    castling |= B_OOO
                    self.ini_rooks[1][0] = rank8.find('r') + 56
                    self.ini_kings[BLACK] = self.kings[BLACK]
            else:
                if char == "K":
                    castling |= W_OO
                elif char == "Q":
                    castling |= W_OOO
                elif char == "k":
                    castling |= B_OO
                elif char == "q":
                    castling |= B_OOO
        self.setCastling(castling)

        # Parse en passant target sqaure
        
        if epChr == "-":
            self.setEnpassant (None) 
        else: self.setEnpassant(cordDic[epChr])
        
        # Parse halfmove clock field
        
        self.fifty = max(int(fiftyChr),0)
        
        # Parse fullmove number
        
        movenumber = int(moveNoChr)*2 -2
        if self.color == BLACK: movenumber += 1
        self.history = []
        self.plyCount = movenumber
    
    def isChecked (self):
        if self.checked == None:
            kingcord = self.kings[self.color]
            self.checked = isAttacked (self, kingcord, 1-self.color)
        return self.checked
    
    def opIsChecked (self):
        if self.opchecked == None:
            kingcord = self.kings[1-self.color]
            self.opchecked = isAttacked (self, kingcord, self.color)
        return self.opchecked
        
    def _addPiece (self, cord, piece, color):
        _setBit = setBit
        self.boards[color][piece] = _setBit(self.boards[color][piece], cord)
        self.friends[color] = _setBit(self.friends[color], cord)
        self.blocker = _setBit(self.blocker, cord)
        
        if piece == PAWN:
            self.pawnhash ^= pieceHashes[color][PAWN][cord]
        elif piece == KING:
            self.kings[color] = cord
        self.hash ^= pieceHashes[color][piece][cord]
        self.arBoard[cord] = piece
    
    def _removePiece (self, cord, piece, color):
        _clearBit = clearBit
        self.boards[color][piece] = _clearBit(self.boards[color][piece], cord)
        self.friends[color] = _clearBit(self.friends[color], cord)
        self.blocker = _clearBit(self.blocker, cord)
        
        if piece == PAWN:
            self.pawnhash ^= pieceHashes[color][PAWN][cord]
        
        self.hash ^= pieceHashes[color][piece][cord]
        self.arBoard[cord] = EMPTY
    
    def setColor (self, color):
        if color == self.color: return
        self.color = color
        self.hash ^= colorHash
    
    def setCastling (self, castling):
        if self.castling == castling: return
        
        if castling & W_OO != self.castling & W_OO:
            self.hash ^= W_OOHash
        if castling & W_OOO != self.castling & W_OOO:
            self.hash ^= W_OOOHash
        if castling & B_OO != self.castling & B_OO:
            self.hash ^= B_OOHash
        if castling & B_OOO != self.castling & B_OOO:
            self.hash ^= B_OOOHash
            
        self.castling = castling
    
    def setEnpassant (self, epcord):
        # Strip the square if there's no adjacent enemy pawn to make the capture
        if epcord != None:
            sideToMove = (epcord >> 3 == 2 and BLACK or WHITE)
            fwdPawns = self.boards[sideToMove][PAWN]
            if sideToMove == WHITE:
                fwdPawns >>= 8
            else:
                fwdPawns <<= 8
            pawnTargets  = (fwdPawns & ~fileBits[0]) << 1;
            pawnTargets |= (fwdPawns & ~fileBits[7]) >> 1;
            if not pawnTargets & bitPosArray[epcord]:
                epcord = None

        if self.enpassant == epcord: return
        if self.enpassant != None:
            self.hash ^= epHashes[self.enpassant & 7]
        if epcord != None:
            self.hash ^= epHashes[epcord & 7]
        self.enpassant = epcord
    
    def applyMove (self, move):
        flag = move >> 12
        fcord = (move >> 6) & 63
        tcord = move & 63
        
        fpiece = self.arBoard[fcord]
        tpiece = self.arBoard[tcord]
        
        color = self.color
        opcolor = 1-self.color
        
        # Castling moves can be represented strangely, so normalize them.
        if flag in (KING_CASTLE, QUEEN_CASTLE):
            side = flag - QUEEN_CASTLE
            fpiece = KING
            tpiece = EMPTY # In FRC, there may be a rook there, but the king doesn't capture it.
            fcord = self.ini_kings[color]
            tcord = fin_kings[color][side]
            rookf = self.ini_rooks[color][side]
            rookt = fin_rooks[color][side]
        
        # Update history
        self.history.append (
            (move, tpiece, self.enpassant, self.castling,
            self.hash, self.fifty, self.checked, self.opchecked)
        )
        
        self.opchecked = None
        self.checked = None
        
        # Capture
        if tpiece != EMPTY:
            self._removePiece(tcord, tpiece, opcolor)
        
        # Remove moving piece(s), then add them at their destination.
        self._removePiece(fcord, fpiece, color)

        if flag in (KING_CASTLE, QUEEN_CASTLE):
            self._removePiece (rookf, ROOK, color)
            self._addPiece (rookt, ROOK, color)
            self.hasCastled[color] = True
        
        if flag == ENPASSANT:
            takenPawnC = tcord + (color == WHITE and -8 or 8)
            self._removePiece (takenPawnC, PAWN, opcolor)
        elif flag in PROMOTIONS:
            # Pretend the pawn changes into a piece before reaching its destination.
            fpiece = flag - 2
                
        self._addPiece(tcord, fpiece, color)

        if fpiece == PAWN and abs(fcord-tcord) == 16:
            self.setEnpassant ((fcord + tcord) / 2)
        else: self.setEnpassant (None)
        
        if tpiece == EMPTY and fpiece != PAWN:
            self.fifty += 1
        else:
            self.fifty = 0
        
        # Clear castle flags
        castling = self.castling
        if fpiece == KING:
            castling &= ~CAS_FLAGS[color][0]
            castling &= ~CAS_FLAGS[color][1]
        elif fpiece == ROOK:
            if fcord == self.ini_rooks[color][0]:
                castling &= ~CAS_FLAGS[color][0]
            elif fcord == self.ini_rooks[color][1]:
                castling &= ~CAS_FLAGS[color][1]
        if tpiece == ROOK:
            if tcord == self.ini_rooks[opcolor][0]:
                castling &= ~CAS_FLAGS[opcolor][0]
            elif tcord == self.ini_rooks[opcolor][1]:
                castling &= ~CAS_FLAGS[opcolor][1]
        self.setCastling(castling)

        self.setColor(opcolor)
        self.plyCount += 1
    
    def popMove (self):
        # Note that we remove the last made move, which was not made by boards
        # current color, but by its opponent
        color = 1 - self.color
        opcolor = self.color
        
        # Get information from history
        move, cpiece, enpassant, castling, \
        hash, fifty, checked, opchecked = self.history.pop()
        
        flag = move >> 12
        fcord = (move >> 6) & 63
        tcord = move & 63
        tpiece = self.arBoard[tcord]
        
        # Castling moves can be represented strangely, so normalize them.
        if flag in (KING_CASTLE, QUEEN_CASTLE):
            side = flag - QUEEN_CASTLE
            tpiece = KING
            fcord = self.ini_kings[color]
            tcord = fin_kings[color][side]
            rookf = self.ini_rooks[color][side]
            rookt = fin_rooks[color][side]

        self._removePiece (tcord, tpiece, color)

        # Put back rook moved by castling
        if flag in (KING_CASTLE, QUEEN_CASTLE):
            self._removePiece (rookt, ROOK, color)
            self._addPiece (rookf, ROOK, color)
            self.hasCastled[color] = False
        
        # Put back captured piece
        if cpiece != EMPTY:
            self._addPiece (tcord, cpiece, opcolor)
        
        # Put back piece captured by enpassant
        if flag == ENPASSANT:
            epcord = color == WHITE and tcord - 8 or tcord + 8
            self._addPiece (epcord, PAWN, opcolor)
            
        # Un-promote pawn
        if flag in PROMOTIONS:
            tpiece = PAWN

        # Put back moved piece
        self._addPiece (fcord, tpiece, color)
        
        
        self.setColor(color)
        
        self.checked = checked
        self.opchecked = opchecked
        self.enpassant = enpassant
        self.castling = castling
        self.hash = hash
        self.fifty = fifty
        self.plyCount -= 1
        
    def __hash__ (self):
        return self.hash
    
    def reprCastling (self):
        if not self.castling:
            return "-"
        else:
            strs = []
            if self.variant == FISCHERRANDOMCHESS:
                if self.castling & W_OO:
                    strs.append(reprCord[self.ini_rooks[0][1]][0].upper())
                if self.castling & W_OOO:
                    strs.append(reprCord[self.ini_rooks[0][0]][0].upper())
                if self.castling & B_OO:
                    strs.append(reprCord[self.ini_rooks[1][1]][0])
                if self.castling & B_OOO:
                    strs.append(reprCord[self.ini_rooks[1][0]][0])
            else:
                if self.castling & W_OO:
                    strs.append("K")
                if self.castling & W_OOO:
                    strs.append("Q")
                if self.castling & B_OO:
                    strs.append("k")
                if self.castling & B_OOO:
                    strs.append("q")
            return "".join(strs)
    
    def __repr__ (self):
        b = reprColor[self.color] + " "
        b += self.reprCastling() + " "
        b += self.enpassant != None and reprCord[self.enpassant] or "-"
        b += "\n"
        rows = [self.arBoard[i:i+8] for i in range(0,64,8)][::-1]
        for r, row in enumerate(rows):
            for i, piece in enumerate(row):
                if piece != EMPTY:
                    sign = reprSign[piece]
                    if bitPosArray[(7-r)*8+i] & self.friends[WHITE]:
                        sign = sign.upper()
                    else: sign = sign.lower()
                    b += sign
                else: b += "."
                b += " "
            b += "\n"
        return b
    
    def asFen (self):
        fenstr = []
        
        rows = [self.arBoard[i:i+8] for i in range(0,64,8)][::-1]
        for r, row in enumerate(rows):
            empty = 0
            for i, piece in enumerate(row):
                if piece != EMPTY:
                    if empty > 0:
                        fenstr.append(str(empty))
                        empty = 0
                    sign = reprSign[piece]
                    if bitPosArray[(7-r)*8+i] & self.friends[WHITE]:
                        sign = sign.upper()
                    else: sign = sign.lower()
                    fenstr.append(sign)
                else:
                    empty += 1
            if empty > 0:
                fenstr.append(str(empty))
            if r != 7:
                fenstr.append("/")
        
        fenstr.append(" ")
    
        fenstr.append(self.color == WHITE and "w" or "b")
        fenstr.append(" ")
        
        fenstr.append(self.reprCastling())
        fenstr.append(" ")
        
        if not self.enpassant:
            fenstr.append("-")
        else:
                fenstr.append(reprCord[self.enpassant])
        fenstr.append(" ")
        
        fenstr.append(str(self.fifty))
        fenstr.append(" ")
        
        fullmove = (self.plyCount)/2 + 1
        fenstr.append(str(fullmove))
        
        return "".join(fenstr)
    
    def clone (self):
        copy = LBoard(self.variant)
        copy.blocker = self.blocker
        
        copy.friends = self.friends[:]
        copy.kings = self.kings[:]
        copy.boards = [self.boards[WHITE][:], self.boards[BLACK][:]]
        
        copy.enpassant = self.enpassant
        copy.color = self.color
        copy.castling = self.castling
        copy.hasCastled = self.hasCastled[:]
        copy.fifty = self.fifty
        copy.plyCount = self.plyCount
        
        copy.checked = self.checked
        copy.opchecked = self.opchecked
        
        copy.arBoard = self.arBoard[:]
        
        copy.hash = self.hash
        copy.pawnhash = self.pawnhash
        
        # We don't need to deepcopy the tuples, as they are imutable
        copy.history = self.history[:]
        
        copy.ini_kings = self.ini_kings[:]
        copy.ini_rooks = [self.ini_rooks[0][:], self.ini_rooks[1][:]]
        return copy
