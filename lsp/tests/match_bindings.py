#!/usr/bin/env python3
"""Match payloads retain types, declaration identity and arm-local scopes."""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from protocol_features import request, send


SOURCE = '''import core::option::Option
import core::result::Result
import core::future::{Context, Future, Poll}
import refrain::api::Client

struct Ticker { symbol: str }
enum Event { Tick(Ticker) }
struct EventFuture {}
impl Future[Result[Event, str]] for EventFuture {
 pub fn poll(self: Self, context: Context) -> Poll[Self, Result[Event, str]] {
  ret Poll::Ready(Result::Ok(Event::Tick(Ticker { "BTCUSDT" })))
 }
}

fn inspect(input: Result[Event, str]) -> str {
 let event = "outer"
 match input {
  Result::Ok(event) => {
   match event {
    Event::Tick(ticker) => {
     let symbol = ticker.symbol
    }
   }
  }
  Result::Err(event) => {
   let message = event
  }
 }
 ret event
}

fn choose(input: Result[str, u32]) -> str {
 let selected = match input {
  Result::Ok(value) => value
  Result::Err(value) => { let code = value "fallback" }
 }
 ret selected
}

async fn inspect_future(pending: EventFuture) {
 match await pending {
  Result::Ok(future_event) => {
   let copy = future_event
  }
  Result::Err(failure) => { let message = failure }
 }
}

fn multiline(input: Result[str, u32]) -> str {
 ret match input {
  Result::Ok(
   text
  ) => text
  Result::Err(_) => "fallback"
 }
}

fn unicode(input: Result[str, u32]) -> str {
 let _emoji = "😀" ret match input { Result::Ok(label) => label Result::Err(_) => "fallback" }
}
async fn imported_future() {
 let client = match await Client::connect() {
  Result::Ok(connected) => connected
  Result::Err(_) => { ret() }
 }
 match await client.next_event() {
  Result::Ok(imported_event) => {
   match imported_event.payload {
    Option::Some(imported_data) => { let received = imported_data }
    Option::None => {}
   }
  }
  Result::Err(_) => {}
 }
}

struct Envelope[T] { value: Option[T] }
fn optional(input: Envelope[str]) {
 match input.value {
  Option::Some(data) => { let copied = data }
  Option::None => {}
 }
}
'''


def main():
    binary = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='encore-lsp-match-bindings-') as directory:
        root = Path(directory)
        (root / 'src').mkdir()
        (root / 'encore.toml').write_text(
            '[project]\nname="match_bindings"\nversion="0.0.0"\ndependencies=[]\n')
        path = root / 'src/main.enq'
        path.write_text(SOURCE)
        (root / 'src/api.enq').write_text('pub import refrain::stream::Client\n')
        (root / 'src/model.enq').write_text(
            'import core::option::Option\npub struct ImportedEvent { payload: Option[str] }\n')
        (root / 'src/stream.enq').write_text(
            'import core::result::Result\n'
            'import core::option::Option\n'
            'import core::future::{Context, Future, Poll}\n'
            'import refrain::model::ImportedEvent\n'
            'pub struct Client {}\n'
            'pub struct ConnectFuture {}\n'
            'pub struct ReadFuture {}\n'
            'impl for Client {\n'
            ' pub fn connect() -> ConnectFuture { ret ConnectFuture {} }\n'
            ' pub fn next_event(self: Self) -> ReadFuture { ret ReadFuture {} }\n'
            '}\n'
            'impl Future[Result[Client,str]] for ConnectFuture {\n'
            ' pub fn poll(self: Self, context: Context) -> Poll[Self,Result[Client,str]] {\n'
            '  ret Poll::Ready(Result::Ok(Client {}))\n'
            ' }\n}\n'
            'impl Future[Result[ImportedEvent,str]] for ReadFuture {\n'
            ' pub fn poll(self: Self, context: Context) -> Poll[Self,Result[ImportedEvent,str]] {\n'
            '  ret Poll::Ready(Result::Ok(ImportedEvent { Option::Some("price") }))\n'
            ' }\n}\n')
        uri = path.as_uri()
        process = subprocess.Popen([binary], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        number = 0

        def call(method, params):
            nonlocal number
            number += 1
            deadline = threading.Timer(30, process.kill)
            deadline.start()
            try:
                return request(process, number, method, params)
            finally:
                deadline.cancel()

        def position(fragment, name, occurrence=0):
            lines = [(line, text) for line, text in enumerate(SOURCE.splitlines())
                     if fragment in text]
            line, text = lines[occurrence]
            return {'line': line, 'character': len(text[:text.index(name)].encode('utf-16-le')) // 2}

        def params(at):
            return {'textDocument': {'uri': uri}, 'position': at}

        def check(fragment, name, typ, declaration_fragment, occurrence=0):
            at = position(fragment, name, occurrence)
            hover = call('textDocument/hover', params(at))
            assert hover and hover['contents']['value'] == name + ': ' + typ, (fragment, hover)
            locations = call('textDocument/definition', params(at))
            expected = position(declaration_fragment, name)
            assert locations and locations[0]['uri'] == uri, (fragment, locations)
            assert locations[0]['range']['start'] == expected, (fragment, locations, expected)

        try:
            call('initialize', {'rootUri': root.as_uri(), 'initializationOptions': {
                'cache': False, 'debounceMs': 0, 'jobs': 1}})
            send(process, {'jsonrpc': '2.0', 'method': 'textDocument/didOpen', 'params': {
                'textDocument': {'uri': uri, 'languageId': 'encore', 'version': 1, 'text': SOURCE}}})
            def hints(start=None, end=None):
                return call('textDocument/inlayHint', {
                    'textDocument': {'uri': uri}, 'range': {
                        'start': start or {'line': 0, 'character': 0},
                        'end': end or {'line': len(SOURCE.splitlines()) + 1, 'character': 0}}})

            def hint_position(fragment, name):
                at = position(fragment, name)
                return {**at, 'character': at['character'] + len(name)}

            items = hints()
            for fragment, name, typ in [
                ('Ok(event)', 'event', 'Event'), ('match event', 'event', 'Event'),
                ('Tick(ticker)', 'ticker', 'Ticker'), ('Err(event)', 'event', 'str'),
                ('Ok(value)', 'value', 'str'), ('Err(value)', 'value', 'u32'),
                ('Ok(future_event)', 'future_event', 'Event'), ('   text', 'text', 'str'),
                ('Ok(label)', 'label', 'str'), ('match input.value', 'value', 'Option[str]'),
                ('Some(data)', 'data', 'str'),
                ('let client', 'client', 'Client'), ('Ok(connected)', 'connected', 'Client'),
                ('Ok(imported_event)', 'imported_event', 'ImportedEvent'),
                ('Some(imported_data)', 'imported_data', 'str'),
            ]:
                at = hint_position(fragment, name)
                matching = [item for item in items if item['position'] == at]
                assert len(matching) == 1 and matching[0]['label'] == ': ' + typ, (fragment, matching)
                assert matching[0]['kind'] == 1, matching
                # Viewport requests include their start and exclude their end.
                assert hints(at, {**at, 'character': at['character'] + 1}) == matching
                assert hints({**at, 'character': at['character'] - 1}, at) == []
            assert hints() == items, 'repeated requests duplicated or changed hints'
            assert len(items) == len({tuple(item['position'].values()) for item in items}), items
            # Plain uses and wildcard payloads do not acquire extra hints.
            plain_use = hint_position('copy = future_event', 'future_event')
            assert not any(item['position'] == plain_use for item in items), items
            for line, text in enumerate(SOURCE.splitlines()):
                if 'Err(_)' in text:
                    wildcard = {'line': line, 'character': len(text[:text.index('_') + 1].encode('utf-16-le')) // 2}
                    assert not any(item['position'] == wildcard for item in items), items
            # Cursor features must work before the diagnostics worker has finished.
            check('Ok(event)', 'event', 'Event', 'Ok(event)')
            check('match event', 'event', 'Event', 'Ok(event)')
            check('Tick(ticker)', 'ticker', 'Ticker', 'Tick(ticker)')
            check('ticker.symbol', 'ticker', 'Ticker', 'Tick(ticker)')
            check('Err(event)', 'event', 'str', 'Err(event)')
            check('message = event', 'event', 'str', 'Err(event)')
            check('ret event', 'event', 'str', 'let event')
            check('Ok(value)', 'value', 'str', 'Ok(value)')
            # The use and declaration share a line; select the use explicitly.
            at = position('Ok(value)', 'value')
            at['character'] += len('value) => ')
            hover = call('textDocument/hover', params(at))
            assert hover['contents']['value'] == 'value: str', hover
            check('Err(value)', 'value', 'u32', 'Err(value)')
            check('Ok(future_event)', 'future_event', 'Event', 'Ok(future_event)')
            check('copy = future_event', 'future_event', 'Event', 'Ok(future_event)')
            check('   text', 'text', 'str', '   text')
            check(') => text', 'text', 'str', '   text')
            check('Ok(label)', 'label', 'str', 'Ok(label)')
            result = call('textDocument/diagnostic', {'textDocument': {'uri': uri}})
            assert result.get('items') == [], result
            # Rename must stay inside this arm and include its payload declaration.
            edit = call('textDocument/rename', {
                **params(position('match event', 'event')), 'newName': 'received'})
            edits = edit['changes'][uri]
            assert {tuple(item['range']['start'].values()) for item in edits} == {
                tuple(position('Ok(event)', 'event').values()),
                tuple(position('match event', 'event').values())}, edit
            call('shutdown', {})
            send(process, {'jsonrpc': '2.0', 'method': 'exit', 'params': {}})
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    print('match payload hover, declaration navigation, shadowing, await, rename and inlay hints: ok')


if __name__ == '__main__':
    main()
