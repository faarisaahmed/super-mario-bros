"""
Make nes-py importable under NumPy 2.

nes-py reads the iNES header into a uint8 array, so `16 * self.header[4]`
stays a numpy uint8 and the later `* 2**10` overflows instead of promoting.
NumPy 1.x silently widened; 2.0 raises. Patch the six size/offset properties
to plain ints at import time rather than editing the installed package.
"""

import nes_py._rom as _rom

_PATCHES = {
    "prg_rom_size": lambda self: 16 * int(self.header[4]),
    "chr_rom_size": lambda self: 8 * int(self.header[5]),
    "prg_rom_start": lambda self: int(self.trainer_rom_stop),
    "prg_rom_stop": lambda self: int(self.prg_rom_start) + int(self.prg_rom_size) * 2 ** 10,
    "chr_rom_start": lambda self: int(self.prg_rom_stop),
    "chr_rom_stop": lambda self: int(self.chr_rom_start) + int(self.chr_rom_size) * 2 ** 10,
}

for _name, _fn in _PATCHES.items():
    setattr(_rom.ROM, _name, property(_fn))
