#!/usr/bin/env python3
"""
Build Chinese V2 binary dictionary and unigrams list for CleverKeys.
Converts Chinese words to Pinyin (a-z) for the normalized lookup index.
"""

import sys
import os
import math
import struct
from pathlib import Path
from collections import defaultdict

try:
    import pypinyin
except ImportError:
    print("Error: pypinyin not installed. Run: pip install pypinyin")
    sys.exit(1)

try:
    import wordfreq
except ImportError:
    print("Error: wordfreq not installed. Run: pip install wordfreq")
    sys.exit(1)


def get_pinyin(word: str) -> str:
    """Convert a Chinese word to lowercase Pinyin (a-z only)."""
    pinyin_list = pypinyin.pinyin(word, style=pypinyin.Style.NORMAL)
    pinyin_str = "".join([item[0] for item in pinyin_list]).lower()
    # Strip any non-a-z characters
    return "".join(c for c in pinyin_str if 'a' <= c <= 'z')


def write_v2_binary(
    output_path: Path,
    lang: str,
    canonical_words: list,  # list of (word, rank)
    normalized_words: list, # list of strings
    accent_map: dict        # normalized -> list of canonical_indices
):
    """Write V2 binary dictionary format (CKDT)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as f:
        header_size = 48

        # Prepare canonical section
        canonical_data = bytearray()
        for word, rank in canonical_words:
            word_bytes = word.encode('utf-8')
            canonical_data += struct.pack('<H', len(word_bytes))  # uint16 length
            canonical_data += word_bytes
            canonical_data += struct.pack('<B', rank)  # uint8 rank

        # Prepare normalized section
        normalized_data = bytearray()
        normalized_data += struct.pack('<I', len(normalized_words))  # count
        for word in normalized_words:
            word_bytes = word.encode('utf-8')
            normalized_data += struct.pack('<H', len(word_bytes))
            normalized_data += word_bytes

        # Prepare accent map section (maps normalized index to canonical index)
        accent_map_data = bytearray()
        for normalized in normalized_words:
            indices = accent_map.get(normalized, [])
            accent_map_data += struct.pack('<B', len(indices))  # uint8 count
            for idx in indices:
                accent_map_data += struct.pack('<I', idx)  # uint32 index

        # Calculate offsets
        canonical_offset = header_size
        normalized_offset = canonical_offset + len(canonical_data)
        accent_map_offset = normalized_offset + len(normalized_data)

        # Write header
        lang_bytes = lang.encode('utf-8')[:4].ljust(4, b'\x00')
        header = struct.pack('<I', 0x54444B43)  # Magic: "CKDT"
        header += struct.pack('<I', 2)  # Version 2
        header += lang_bytes  # Language ("zh\0\0")
        header += struct.pack('<I', len(canonical_words))  # Word count
        header += struct.pack('<I', canonical_offset)
        header += struct.pack('<I', normalized_offset)
        header += struct.pack('<I', accent_map_offset)
        header += b'\x00' * 20  # Reserved (20 bytes)

        f.write(header)
        f.write(canonical_data)
        f.write(normalized_data)
        f.write(accent_map_data)

    print(f"Wrote {output_path}: {len(canonical_words)} canonical words, "
          f"{len(normalized_words)} normalized Pinyin forms, "
          f"{sum(len(v) for v in accent_map.values())} mappings")


def main():
    lang = 'zh'
    word_count = 50000

    print(f"Retrieving top {word_count} Chinese words from wordfreq...")
    raw_words = []
    
    # Try large first
    try:
        word_iter = wordfreq.iter_wordlist(lang, wordlist='large')
    except Exception:
        word_iter = wordfreq.iter_wordlist(lang, wordlist='best')

    for word in word_iter:
        # Keep only words containing Chinese characters
        if all('\u4e00' <= char <= '\u9fff' for char in word):
            raw_words.append(word)
            if len(raw_words) >= word_count:
                break

    print(f"Loaded {len(raw_words)} raw Chinese words. Processing Pinyin and frequencies...")

    # Process words, get frequencies and convert to pinyin
    words_data = []  # List of (chinese_word, pinyin, frequency)
    max_freq = 0.0

    for word in raw_words:
        freq = wordfreq.word_frequency(word, lang) * 1e8
        if freq > max_freq:
            max_freq = freq

        pinyin = get_pinyin(word)
        # We need pinyin to be a valid swipe trajectory of letters a-z, length >= 2
        if len(pinyin) >= 2 and pinyin.isalpha():
            words_data.append((word, pinyin, freq))

    # Sort words_data by frequency descending
    words_data.sort(key=lambda x: x[2], reverse=True)

    # De-duplicate: if multiple Chinese words have the same Pinyin, that's fine (homophones)
    # The dictionary maps one normalized Pinyin to multiple canonical Chinese characters.
    canonical_words = []  # List of (chinese, rank)
    normalized_set = set()
    accent_map = defaultdict(list)

    # Fill canonical_words and map them
    for idx, (chinese, pinyin, freq) in enumerate(words_data):
        # Convert frequency to rank (0-255)
        log_freq = math.log(freq + 1)
        log_max = math.log(max_freq + 1)
        rank = int((1.0 - log_freq / log_max) * 255)
        rank = max(0, min(255, rank))

        canonical_words.append((chinese, rank))
        normalized_set.add(pinyin)

    # Convert normalized set to sorted list
    normalized_words = sorted(list(normalized_set))

    # Create mapping from normalized pinyin to canonical index
    # We do a fast lookup by indexing the canonical list we just built
    for canonical_idx, (chinese, pinyin, freq) in enumerate(words_data):
        accent_map[pinyin].append(canonical_idx)

    # Output paths
    base_dir = Path(__file__).parent.parent.resolve()
    dict_output = base_dir / "src/main/assets/dictionaries/zh_enhanced.bin"
    unigrams_output = base_dir / "src/main/assets/unigrams/zh_unigrams.txt"

    # Write binary dictionary
    write_v2_binary(dict_output, lang, canonical_words, normalized_words, accent_map)

    # Generate top 5000 unigrams for language detection
    print(f"Generating top 5000 unigrams for language detection...")
    unigrams_output.parent.mkdir(parents=True, exist_ok=True)
    
    # Unigrams file contains the top Chinese words (characters)
    unigrams_count = min(5000, len(words_data))
    with open(unigrams_output, 'w', encoding='utf-8') as f:
        # Write top N Chinese words
        for i in range(unigrams_count):
            f.write(words_data[i][0] + '\n')

    print(f"Wrote {unigrams_count} unigrams to {unigrams_output}")


if __name__ == '__main__':
    main()
