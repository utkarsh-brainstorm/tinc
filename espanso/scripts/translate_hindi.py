#!/usr/bin/env python3
"""
translate_hindi.py - Fast Hindi translation/transliteration for Espanso
Modes:
  hi  = Full grammatical translation (English/Hinglish → Hindi)
  hd  = Literal transliteration only (Romanized Hindi → Hindi script, no vocab change)
  hu  = Hinglish → Hindi (same meaning, Hindi script via transliteration API)
"""
import os
import sys
import json
import urllib.request
import urllib.parse

TIMEOUT = 4

def translate_to_hindi(text):
    """Full grammatical translation using Google Translate API (free endpoint)."""
    try:
        encoded = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=hi&dt=t&q={encoded}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode('utf-8')
        data = json.loads(response)
        # Collect all translated parts
        result = ""
        for part in data[0]:
            if part and part[0]:
                result += part[0]
        return result.strip() if result.strip() else text
    except Exception:
        return text

def transliterate_to_devanagari(text):
    """Convert Romanized Hindi/Hinglish to Devanagari script without grammar change.
    Uses Google Input Tools API for accurate Hinglish → Devanagari conversion."""
    try:
        # Split into words for better transliteration accuracy
        words = text.split()
        result_words = []
        for word in words:
            encoded = urllib.parse.quote(word)
            url = f"https://inputtools.google.com/request?text={encoded}&itc=hi-t-i0-und&num=1&cp=0&cs=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode('utf-8')
            data = json.loads(response)
            if data[0] == "SUCCESS" and data[1]:
                hi_word = data[1][0][1][0]
                result_words.append(hi_word)
            else:
                result_words.append(word)
        return " ".join(result_words)
    except Exception:
        return text

def hinglish_to_hindi(text):
    """Convert Hinglish sentence to Hindi using transliteration API.
    Same as transliterate but works word-by-word for better sentence handling."""
    return transliterate_to_devanagari(text)

if __name__ == "__main__":
    # Read mode and text from environment variables (set by Espanso)
    mode = os.environ.get('ESPANSO_MODE', '').strip()
    text = os.environ.get('ESPANSO_TEXT', '').strip()

    if not mode or not text:
        # Fallback: try reading from argv (for debugging)
        if len(sys.argv) >= 3:
            mode = sys.argv[1].strip()
            text = sys.argv[2].strip()

    if not text:
        sys.exit(0)

    if mode == 'hi':
        result = translate_to_hindi(text)
    elif mode == 'hd':
        result = transliterate_to_devanagari(text)
    elif mode == 'hu':
        result = hinglish_to_hindi(text)
    else:
        result = translate_to_hindi(text)

    # Output with no trailing newline so Espanso places it cleanly
    print(result, end="")
