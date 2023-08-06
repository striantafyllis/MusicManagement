#!/usr/bin/env python

import sys
import argparse
import re
import time
import os.path

import rekordbox
import google_sheet
import spotify_library

class RekordboxState:
    def __init__(self,
                 collection: rekordbox.Collection,
                 playlists: dict[str, rekordbox.Playlist]):
        self.collection = collection
        self.playlists = playlists

        self.main_library = playlists.get('Main Library')
        self.second_look = playlists.get('second look')
        self.backlog = playlists.get('backlog')
        self.other = playlists.get('other / non-house')
        return

def read_rekordbox(rekordbox_xml):
    collection, playlists = rekordbox.parse_library(rekordbox_xml)

    return RekordboxState(collection, playlists)

def rekordbox_stats(rekordbox_state: RekordboxState):
    print('Rekordbox:')
    print('  Total tracks: %d' % len(rekordbox_state.collection.tracks_by_id))

    if rekordbox_state.main_library is None:
        sys.stderr.write("  WARNING: No 'Main Library' playlist\n")
    else:
        print('  Main Library tracks: %d' % len(rekordbox_state.main_library.tracks))

    if rekordbox_state.second_look is None:
        sys.stderr.write("  WARNING: No 'second look' playlist\n")
    else:
        print('  Second look tracks: %d' % len(rekordbox_state.second_look.tracks))

    if rekordbox_state.backlog is None:
        sys.stderr.write("  WARNING: No 'backlog' playlist")
    else:
        print('  Backlog tracks: %d' % len(rekordbox_state.backlog.tracks))

    if rekordbox_state.other is None:
        sys.stderr.write("  WARNING: No 'other / non-house' playlist")
    else:
        print('  Other/non-house tracks: %d' % len(rekordbox_state.other.tracks))

    time.sleep(0.1)

def rekordbox_sanity_checks(rekordbox_state):
    # check that each track is in at most one of the 4 main lists
    num_errors = 0
    for track in rekordbox_state.collection.all_tracks_by_id():
        containing_playlists = []
        if track in rekordbox_state.main_library:
            containing_playlists.append('Main Library')
        if track in rekordbox_state.second_look:
            containing_playlists.append('second look')
        if track in rekordbox_state.backlog:
            containing_playlists.append('backlog')
        if track in rekordbox_state.other:
            containing_playlists.append('other / non-house')

        if len(containing_playlists) == 0:
            sys.stderr.write('Track is not in any top-level playlist: %s\n' % track)
            num_errors += 1
        elif len(containing_playlists) > 1:
            sys.stderr.write('Track is in multiple top-level playists %s: %s\n' % (containing_playlists, track))
            num_errors += 1

    if num_errors > 0:
        sys.stderr.write('*** Fix the above %d errors manually! ***\n' % num_errors)
        sys.exit(1)

    return

def sheet_stats(sheet: google_sheet.Sheet):
    print("Google sheet ID='%s' page='%s': %d entries" % (
        sheet.id,
        sheet.page,
        len(sheet.tracks)
    ))
    time.sleep(0.1)
    return


def cross_reference_rekordbox_to_google_sheet(
        rekordbox_state: RekordboxState,
        sheet: google_sheet.Sheet):

    num_errors = 0
    num_missing_ids = 0

    for track_info in sheet.tracks:
        if track_info.rekordbox_id is not None:
            track = rekordbox_state.collection.tracks_by_id.get(track_info.rekordbox_id)

            if track is None:
                sys.stderr.write('Sheet row %d: track ID %d not found in Rekordbox\n' % (
                    track_info.row_num, track_info.rekordbox_id))
                num_errors += 1
        else:
            # try to match by artists and title
            num_missing_ids += 1
            artists = frozenset(track_info.artists)

            track = rekordbox_state.collection.tracks_by_artists_and_name[artists].get(track_info.title)

            if track is None:
                sys.stderr.write("Sheet row %d: track artists '%s' title '%s' not found in Rekordbox\n" % (
                    track_info.row_num, track_info.artists, track_info.title))
                num_errors += 1
            else:
                track_info.rekordbox_id = track.id
                track_info.dirty_fields.append('rekordbox_id')
        TEST_SPREADSHEET_ID = '1pvJC8ThHEHHnz8-BRiS34pIDcq3j62Asj52cxP4Mwdk'

        if track is not None:
            if track.track_info is not None:
                sys.stderr.write("Rekordbox track artists '%s' title '%s' is associated with 2 sheet entries: rows %d and %d" % (
                    track.artists,
                    track.title,
                    track.track_info.row_num,
                    track_info.row_num
                ))
                num_errors += 1
            else:
                track_info.track = track
                track.track_info = track_info

    if num_errors > 0:
        sys.stderr.write('*** Fix the above %d errors manually! ***\n' % num_errors)
        sys.exit(1)

    if num_missing_ids > 0:
        sys.stderr.write('%d missing track IDs in Google sheet!\n' % num_missing_ids)
        sys.stderr.write('Write missing IDs? (y/n) >')
        sys.stderr.flush()

        reply = sys.stdin.readline().strip()

        if reply.upper() == 'Y' or reply.upper() == 'YES':
            updated_cells = sheet.write_back()
            sys.stderr.write('*** Wrote %d missing IDs; verify manually! ***\n' % updated_cells)
            # sys.exit(1)
        else:
            sys.stderr.write('*** Fix missing IDs first! ***\n')
            sys.exit(1)

    return


def sheet_vs_rekordbox_sanity_checks(
        sheet: google_sheet.Sheet,
        rekordbox_state: RekordboxState):

    num_errors = 0
    num_tracks_missing_from_google_sheet = 0

    for track_info in sheet.tracks:
        if track_info.track not in rekordbox_state.main_library:
            sys.stderr.write('%s is in the Google sheet but not in Rekordbox Main Library\n' % track_info)
            num_errors += 1

    for track in rekordbox_state.main_library.tracks:
        if track.track_info is None:
            sys.stderr.write('%s is in Rekordbox Main Library but not in the Google sheet; adding.\n' % track)
            track_info = google_sheet.TrackInfo()
            for field in sheet.Track_field_to_col_num.keys():
                setattr(track_info, field, getattr(track, field))
            track_info.dirty_fields = list(sheet.Track_field_to_col_num.keys())
            sheet.add_track(track_info)
            track.track_info = track_info
            num_tracks_missing_from_google_sheet += 1

    if num_errors > 0:
        sys.stderr.write('*** Fix the above %d errors manually! ***\n' % num_errors)
        # sys.exit(1)

    if num_tracks_missing_from_google_sheet > 0:
        sys.stderr.write('%d tracks missing from Google sheet!\n' % num_tracks_missing_from_google_sheet)
        sys.stderr.write('Add missing tracks? (y/n) >')
        sys.stderr.flush()

        reply = sys.stdin.readline().strip()

        if reply.upper() == 'Y' or reply.upper() == 'YES':
            updated_cells = sheet.write_back()
            sys.stderr.write('*** Added %d missing tracks (%d cells); verify manually! ***\n' % (
                num_tracks_missing_from_google_sheet, updated_cells))
            # sys.exit(1)
        else:
            sys.stderr.write('*** Fix missing tracks first! ***\n')
            sys.exit(1)

    num_mismatched_fields = 0

    for track_info in sheet.tracks:
        for field in sheet.Track_field_to_col_num.keys():
            sheet_value = getattr(track_info, field)
            rekordbox_value = getattr(track_info.track, field)
            if sheet_value != rekordbox_value:
                sys.stderr.write("%s: field %s has value '%s' in Google sheet but '%s' in Rekordbox\n" % (
                    track_info, field, sheet_value, rekordbox_value
                ))
                num_mismatched_fields += 1

                setattr(track_info, field, rekordbox_value)
                track_info.dirty_fields.append(field)

    if num_mismatched_fields > 0:
        sys.stderr.write('%d mismatching fields in Google sheet!\n' % num_mismatched_fields)
        sys.stderr.write('Correct mismatched fields? (y/n) >')
        sys.stderr.flush()

        reply = sys.stdin.readline().strip()

        if reply.upper() == 'Y' or reply.upper() == 'YES':
            updated_cells = sheet.write_back()
            sys.stderr.write('*** Corrected %d mismatched fields; verify manually! ***\n' % updated_cells)
            # sys.exit(1)
        else:
            sys.stderr.write('*** Fix mismatched fields first! ***\n')
            sys.exit(1)


def tokenize(text):
    tokens = []

    while text != '':
        # eat whitespace
        m = re.match('\s*', text)
        text = text[m.end():]

        # match:
        # - operators - ==, <, >, <=, >=
        # - identifiers
        # - integers
        # - single-quoted strings
        # - double-quoted strings
        m = re.match(r"\(|\)|==|!=|<=|>=|<|>|&|\||[A-Za-z_][A-Za-z_0-9]*|[1-9][0-9]*|'[^']*'|\"[^\"]*\"", text)
        if m:
            tokens.append(m.group(0))
            text = text[m.end():]
        else:
            raise Exception("Unparseable suffix: '%s'" % text)

    return tokens

def convert_field_name(sheet, token):
    # see if it's a field name of the Track class
    track_field = google_sheet.col_name_to_Track_field.get(token)
    if track_field is not None:
        return 'track.%s' % track_field

    # otherwise, try to find it in the TrackInfo attributes
    if token in sheet.header:
        return "track.track_info.attributes.get('%s')" % token

    raise Exception("Unrecognizable field: '%s'" % token)

def eval_query(
        rekordbox_state: RekordboxState,
        sheet: google_sheet.Sheet,
        query_text: str
):
    tokens = tokenize(query_text)
    # print('Tokens: %s' % tokens)

    for i in range(len(tokens)):
        token = tokens[i]

        # convert boolean operators
        if token == '&':
            tokens[i] = 'and'
        elif token == '|':
            tokens[i] = 'or'
        elif re.match(r'[A-Za-z_][A-Za-z_0-9]*', token):
            # identifier
            if token == 'and' or token == 'or' or token == 'not':
                # boolean operator
                pass
            else:
                tokens[i] = convert_field_name(sheet, token)
        elif token[0] == '"':
            # double-quoted string; field name
            tokens[i] = convert_field_name(sheet, token[1:-1])

    python_expr = ' '.join(tokens)

    # print("Python expression: '%s'" % python_expr)

    compiled_python_expr = compile(python_expr, '<input>', 'eval')

    result = []
    for track in rekordbox_state.main_library.tracks:
        # TODO this should not be necessary if sanity checks have passed
        if track.track_info is None:
            continue
        eval_result = eval(compiled_python_expr)
        if eval_result:
            result.append(track)

    return result

def write_m3u_playlist(playlist_filename, tracklist):
    if not playlist_filename.endswith('.m3u8'):
        playlist_filename += '.m3u8'

    playlist_file = open(playlist_filename, 'w')

    playlist_file.write('#EXTM3U\n')

    for track in tracklist:
        playlist_file.write('#EXTINF:%d,%s \u2013 %s\n' % (
            track.duration,
            track.artist_orig,
            track.title
        ))
        playlist_file.write(track.location + '\n')

    playlist_file.close()

    print("Wrote file '%s' (%d tracks)" % (playlist_filename, len(tracklist)))


def handle_playlist_cmd(playlist_cmd, playlist_dir, tracklist):
    m = re.match('PLAYLIST\s+([A-Z].*)', playlist_cmd, re.IGNORECASE)
    if not m:
        raise Exception('Malformed PLAYLIST command')
    playlist_name = m.group(1)
    playlist_filename = os.path.join(playlist_dir, playlist_name)

    if tracklist is None:
        raise Exception('No previous playlist')

    write_m3u_playlist(playlist_filename, tracklist)
    tracklist = None

def handle_spotify_cmd(spotify_cmd, rekordbox_state, tracklist):
    tokens = tokenize(spotify_cmd)

    assert len(tokens) >= 1 and tokens[0].upper() == 'SPOTIFY'

    tokens = tokens[1:]

    if len(tokens) == 0:
        raise Exception('No spotify command')

    if tokens[0].upper() in ['FIND', 'SEARCH']:
        handle_spotify_search(tokens[1:], rekordbox_state, tracklist)
        return

    raise Exception("Unknown spotify command: ''" % ' '.join(tokens))

def handle_spotify_search(tokens,
                          rekordbox_state : RekordboxState,
                          tracklist: list(rekordbox.Track)):
    if len(tokens) == 0 or len(tokens) == 1 and tokens[0].upper() in ['ALL', 'LIBRARY']:
        search_tracklist = rekordbox_state.main_library
    elif len(tokens) == 1 and tokens[0].upper() == 'QUERY':
        search_tracklist = tracklist

    search_trackinfo_list = [
        track.track_info
        for track in search_tracklist
        if track.track_info is not None
           and track.track_info.spotify_uri is None
    ]

    if len(search_trackinfo_list) == 0:
        sys.stderr.write('No tracks to search for!')

    print('Searching for %d tracks ...' % len(search_trackinfo_list))

    for track_info in search_trackinfo_list:
        hits = spotify_library.search(track_info)

    return




def main():
    parser = argparse.ArgumentParser(
        prog='library_organizer.py',
        description='Organizes my music library between Rekordbox, Spotify and YouTube with help from some Google docs'
    )
    parser.add_argument('--playlist_dir', default=rekordbox.default_playlist_dir)
    parser.add_argument('--rekordbox_xml', default=rekordbox.default_rekordbox_xml)
    parser.add_argument('--google_sheet_id', default=google_sheet.DEFAULT_SPREADSHEET_ID)
    parser.add_argument('--google_sheet_page', default=google_sheet.DEFAULT_SPREADSHEET_PAGE)

    args = parser.parse_args()

    playlist_dir = args.playlist_dir

    rekordbox_state = read_rekordbox(args.rekordbox_xml)

    sheet = google_sheet.parse_sheet(args.google_sheet_id, args.google_sheet_page)

    rekordbox_stats(rekordbox_state)
    rekordbox_sanity_checks(rekordbox_state)

    sheet_stats(sheet)

    cross_reference_rekordbox_to_google_sheet(rekordbox_state, sheet)

    sheet_vs_rekordbox_sanity_checks(sheet, rekordbox_state)

    print('Ready to accept queries')
    tracklist = None
    while (True):
        sys.stdout.write('> ')
        sys.stdout.flush()
        query_text = sys.stdin.readline()

        if query_text == '':
            # EOF
            break

        query_text = query_text.strip()

        if query_text == '':
            continue

        try:
            if re.match(r'q|quit|exit$', query_text, re.IGNORECASE):
                break

            if re.match(r'playlist\s+', query_text, re.IGNORECASE):
                handle_playlist_cmd(query_text, playlist_dir, tracklist)
            elif re.match(r'spotify\s+', query_text, re.IGNORECASE):
                handle_spotify_cmd(query_text, rekordbox_state, tracklist)
            else:
                tracklist = eval_query(rekordbox_state, sheet, query_text)
                for track in tracklist:
                    print('%s \u2013 %s' % (track.artist_orig, track.title))
                print('(%d tracks)' % len(tracklist))
        except Exception as e:
            sys.stdout.flush()
            sys.stderr.write('Query "%s" failed: %s\n' % (query_text, e))
            sys.stderr.flush()
            time.sleep(0.1)
            print()
            continue

    return 0




if __name__ == '__main__':
    exit_value = main()
    sys.exit(exit_value)
