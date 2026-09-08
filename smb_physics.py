"""
Physics constants lifted verbatim from the Super Mario Bros. 6502 disassembly.

Source: smbdis.asm (doppelganger's disassembly, the copy in
MitchellSternke/SuperMarioBros-C). Line numbers in the comments refer to that
file so every number here can be traced back rather than eyeballed off a
recording. See docs/physics.md for the full derivation.

Two fixed-point formats are involved, and mixing them up is the easy mistake:

  X speed  is a signed byte in 4.4 -- whole pixels per frame in the high
           nybble, sixteenths in the low. $18 is 1.5 px/frame.
  Y speed  is a signed byte of *whole* pixels per frame, with a separate
           8-bit fraction (Y_MoveForce). $fc is -4 px/frame.

Gravity ("movement force") is always in 1/256 px/frame/frame.
"""

# The NES ran at ~60.0988 Hz; 60 is close enough and keeps the numbers clean.
FRAME_TIME = 1.0 / 60.0

# --- horizontal ------------------------------------------------------------
# MaxLeftXSpdData / MaxRightXSpdData, smbdis.asm:6026-6031. Index 0 is
# running, 1 walking, 2 swimming; index 3 on the right is the pipe intro.
MAX_LEFT_X_SPEED = (-0x28, -0x18, -0x10)      # $d8, $e8, $f0
MAX_RIGHT_X_SPEED = (0x28, 0x18, 0x10, 0x0c)  # $28, $18, $10, $0c

# FrictionData, smbdis.asm:6033. This is the per-frame accelerator, in
# 1/256 of an X-speed unit -- i.e. 1/4096 px/frame/frame. It doubles while
# skidding (facing direction != moving direction).
FRICTION = (0xe4, 0x98, 0xd0)                 # run, walk, decelerate

# Speed at or above which the "decelerate" friction row is used instead of
# the walking one (X_Physics, smbdis.asm:6163).
FAST_FRICTION_SPEED = 0x21
# Airborne speed at or above which running max-speed/friction still apply.
AIR_RUN_SPEED = 0x19
# B held sets this many frames of grace where running still applies.
RUNNING_TIMER_SET = 0x0a
# GetPlayerAnimSpeed, smbdis.asm:6200-6216.
RUN_SPEED_THRESHOLD = 0x1c    # at/above this, RunningSpeed latches
SKID_TURNAROUND_SPEED = 0x0b  # below this while skidding, speed snaps to 0

# --- vertical --------------------------------------------------------------
# JumpMForceData / FallMForceData / PlayerYSpdData / InitMForceData,
# smbdis.asm:6014-6024. Indices 5-6 are swim/whirlpool and are unused here.
#
# The row is chosen by Player_XSpeedAbsolute at the moment of the jump
# (ProcJumping, smbdis.asm:6100-6112), which is why running jumps go higher.
JUMP_SPEED_THRESHOLDS = (0x09, 0x10, 0x19, 0x1c)
JUMP_M_FORCE = (0x20, 0x20, 0x1e, 0x28, 0x28)    # gravity while rising, A held
FALL_M_FORCE = (0x70, 0x70, 0x60, 0x90, 0x90)    # gravity once A is released
PLAYER_Y_SPEED = (-4, -4, -4, -5, -5)            # launch speed, whole px/frame
INIT_M_FORCE = (0x00, 0x00, 0x00, 0x00, 0x00)

# MovePlayerVertically, smbdis.asm:7592 -- terminal velocity.
MAX_FALL_SPEED = 4
# DiffToHaltJump, smbdis.asm:6114. Releasing A before rising this far does
# not cut the jump, so a one-frame tap still gets off the ground.
DIFF_TO_HALT_JUMP = 1

# --- stomp -----------------------------------------------------------------
# SBnce, smbdis.asm:11512. A goomba (ID $06 < $09) reaches this via
# ChkForDemoteKoopa -> HandleStompedShellE. Nothing else is touched, so the
# bounce inherits the gravity of whatever jump he was already in -- which is
# how "hold A for a higher bounce" falls out for free.
STOMP_BOUNCE_Y_SPEED = -4     # $fc

# --- death -----------------------------------------------------------------
# KillPlayer, smbdis.asm:11427-11434.
DEATH_Y_SPEED = -4            # $fc
# SetKRout sets TimerControl to $ff; PlayerDeath (smbdis.asm:5766) refuses to
# run until it drops below $f0, and it ticks down once a frame -- so he hangs
# motionless for 16 frames before the arc starts.
DEATH_FREEZE_FRAMES = 0xff - 0xf0 + 1
# LRAir, smbdis.asm:7546-7550: while the death routine ($0b) is the active
# game engine subroutine, VerticalForce is overwritten with $28 every frame.
# That, not the jump/fall tables, is what shapes the death arc.
DEATH_VERTICAL_FORCE = 0x28

# --- background collision --------------------------------------------------
# PlayerBGCollision does not test a rectangle against tiles. It samples seven
# single points around the player and looks up the metatile under each:
#
#     head, foot-left, foot-right, then two points down each side.
#
# BlockBufferAdderData (smbdis.asm:13027) picks which group of seven applies.
# Small Mario -- the only size implemented -- uses base $0e.
BLOCK_ADDER_BASE_SMALL = 0x0E

# BlockBuffer_X_Adder / BlockBuffer_Y_Adder, smbdis.asm:13030-13040. Offsets
# are from Player_X_Position / Player_Y_Position, not from the bounding box.
BLOCK_X_ADDER = (
    0x08, 0x03, 0x0c, 0x02, 0x02, 0x0d, 0x0d, 0x08,
    0x03, 0x0c, 0x02, 0x02, 0x0d, 0x0d, 0x08, 0x03,
    0x0c, 0x02, 0x02, 0x0d, 0x0d, 0x08, 0x00, 0x10,
    0x04, 0x14, 0x04, 0x04,
)
BLOCK_Y_ADDER = (
    0x04, 0x20, 0x20, 0x08, 0x18, 0x08, 0x18, 0x02,
    0x20, 0x20, 0x08, 0x18, 0x08, 0x18, 0x12, 0x20,
    0x20, 0x18, 0x18, 0x18, 0x18, 0x18, 0x14, 0x14,
    0x06, 0x06, 0x08, 0x10,
)

# PlayerBGUpperExtent, smbdis.asm:11899 -- indexed by player size, so $10 for
# small. Above this the head check is skipped entirely.
PLAYER_BG_UPPER_EXTENT_SMALL = 0x10

# HeadChk ignores a hit whose Y low-nybble is under this (smbdis.asm:11955).
HEAD_LOW_NYBBLE_MIN = 0x04
# ChkFootMTile lands the player below this, and treats it as a wall at or
# above it (smbdis.asm:12010).
FOOT_LOW_NYBBLE_MAX = 0x05

# Where Player_X/Y_Position sits relative to the hitbox we store. Straight out
# of BoundBoxCtrlData row 1 ($03,$14,$0d,$20): the box starts 3px right of the
# player's X and 20px below their Y.
HITBOX_ORIGIN_DX = 0x03
HITBOX_ORIGIN_DY = 0x14

# --- enemies ---------------------------------------------------------------
# NormalXSpdData, smbdis.asm:8163. $f8 is -8 in the same 4.4 format as the
# player's, so an ordinary goomba shuffles along at half a pixel a frame.
# The second entry is the hard-mode (second quest) speed.
ENEMY_WALK_X_SPEED = (-0x08, -0x0c)           # -0.5, -0.75 px/frame

# MoveD_EnemyVertically -> SetHiMax, smbdis.asm:7599-7644. Enemies fall harder
# than the player but top out slower: 3 px/frame against the player's 4.
ENEMY_GRAVITY = 0x3d                          # 0.238 px/frame/frame
ENEMY_MAX_FALL_SPEED = 3

# --- squashed goomba -------------------------------------------------------
# HandleStompedShellE (smbdis.asm:11509) sets EnemyIntervalTimer to $10, and
# ChkKillGoomba (smbdis.asm:9360) erases the goomba once that timer reads $0e
# -- two decrements. Interval timers only tick when IntervalTimerControl
# wraps, which it does every 21 frames (DecTimers, smbdis.asm:789-794).
SQUASH_TIMER_SET = 0x10
SQUASH_TIMER_KILL = 0x0e
INTERVAL_TIMER_PERIOD = 0x14 + 1   # 21 frames


def signed_byte(value):
    """Reinterpret the low 8 bits of `value` as a signed byte."""
    value &= 0xff
    return value - 0x100 if value >= 0x80 else value


def jump_index(x_speed_absolute):
    """Row of the jump tables to use, picked by horizontal speed exactly as
    ProcJumping does (smbdis.asm:6100-6112)."""
    index = 0
    for threshold in JUMP_SPEED_THRESHOLDS:
        if x_speed_absolute < threshold:
            break
        index += 1
    return index
