import unittest

import __builtin__
__builtin__.__dict__['_'] = lambda s: s

from pychess.Utils.lutils.lmovegen import genAllMoves, genCheckEvasions
from pychess.Utils.lutils.LBoard import LBoard
from pychess.Utils.lutils.bitboard import toString
from pychess.Utils.lutils.ldata import *

from pychess.Utils.lutils.lmove import toSAN
from pychess.Utils.const import *

MAXDEPTH = 2

class FindMovesTestCase(unittest.TestCase):
    """Move generator test using perftsuite.epd from
       http://www.albert.nu/programs/sharper/perft.htm"""
    
    def perft(self, board, depth):
        if depth == 0:
            self.count += 1
            return
        
        if board.isChecked():
            # If we are checked we can use the genCheckEvasions function as well
            # as genAllMoves. Here we try both functions to ensure they return
            # the same result.
            nmoves = []
            for nmove in genAllMoves(board):
                board.applyMove(nmove)
                if board.opIsChecked():
                    board.popMove()
                    continue
                nmoves.append(nmove)
                board.popMove()
            
            cmoves = []
            
            for move in genCheckEvasions(board):
                board.applyMove(move)
                cmoves.append(move)
                board.popMove()
            
            # This is not any kind of alphaBeta sort. Only int sorting, to make
            # comparison possible
            nmoves.sort()
            cmoves.sort()
            
            if nmoves == cmoves:
                for move in cmoves:
                    board.applyMove(move)
                    self.perft(board, depth-1)
                    board.popMove()
            else:
                print board
                print "nmoves"
                for move in nmoves:
                    print toSAN (board, move)
                print "cmoves"
                for move in cmoves:
                    print toSAN (board, move)
                self.assertEqual(nmoves, cmoves)
                
        #if isCheck(board, board.color):
        #    for move in genCheckEvasions(board):
        #        board.applyMove(move)
        #        self.perft(board, depth-1)
        #        board.popMove()
        else:
            for move in genAllMoves(board):
                board.applyMove(move)
                if board.opIsChecked():
                    board.popMove()
                    continue
                #if depth == 5:
                #board.popMove()
                #print "   "*(2-depth)+ltoSAN (board, move)
                #board.applyMove(move)
                self.perft(board, depth-1)
                board.popMove()
    
    def setUp(self):
        self.positions = []
        for line in open('gamefiles/perftsuite.epd'):
            parts = line.split(";")
            depths = [int(s[3:].rstrip()) for s in parts[1:]]
            self.positions.append( (parts[0], depths) )
    
    def testMovegen(self):
        """Testing move generator with several positions"""
        print
        board = LBoard ()
        for i, (pos, depths) in enumerate(self.positions):
            print i+1, "/", len(self.positions), "-", pos
            
            board.applyFen(pos)
            hash = board.hash
            
            for depth, suposedMoveCount in enumerate(depths):
                if depth+1 > MAXDEPTH: break
                self.count = 0
                print "searching depth %d for %d moves" % (depth+1, suposedMoveCount)
                self.perft (board, depth+1)
                self.assertEqual(board.hash, hash)
                self.assertEqual(self.count, suposedMoveCount)
            
if __name__ == '__main__':
    unittest.main()
