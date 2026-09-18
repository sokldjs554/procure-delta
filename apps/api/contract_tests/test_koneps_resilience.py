"""Offline adapter regressions: real adapter + synthetic HTTP, without a database."""
from __future__ import annotations

import copy
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.sources.http import ResilientHttpClient
from app.sources.koneps import KonepsSourceAdapter, map_payload

FIXTURE = Path(__file__).parents[1] / 'tests/sources/fixtures/koneps_services_synthetic.json'


def fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_nonempty_page_must_not_skip_remaining_records(self) -> None:
        body = fixture()
        body['response']['body'].update(totalCount=3, numOfRows=2)
        async with ResilientHttpClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=body)
        )) as client:
            with self.assertRaisesRegex(ValueError, 'pagination'):
                await KonepsSourceAdapter(service_key='synthetic', client=client,
                                          page_size=2).discover(None)

    async def test_wrong_page_echo_cannot_advance_checkpoint(self) -> None:
        body = fixture()
        body['response']['body']['pageNo'] = 2
        async with ResilientHttpClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=body)
        )) as client:
            with self.assertRaisesRegex(ValueError, 'pagination'):
                await KonepsSourceAdapter(service_key='synthetic', client=client).discover(None)

    async def test_wrong_page_size_echo_cannot_advance_checkpoint(self) -> None:
        body = fixture()
        body['response']['body']['numOfRows'] = 50
        async with ResilientHttpClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=body)
        )) as client:
            with self.assertRaisesRegex(ValueError, 'pagination'):
                await KonepsSourceAdapter(service_key='synthetic', client=client).discover(None)

    async def test_boolean_total_is_not_a_valid_count(self) -> None:
        body = fixture()
        body['response']['body']['totalCount'] = True
        async with ResilientHttpClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=body)
        )) as client:
            with self.assertRaises(ValueError):
                await KonepsSourceAdapter(service_key='synthetic', client=client).discover(None)

    async def test_invalid_cursor_is_rejected_before_network(self) -> None:
        calls = []
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=fixture())
        invalid = [
            {'mode': '2', 'page': 1, 'start': '202609150000', 'end': '202609160000'},
            {'mode': '1', 'page': 0, 'start': '202609150000', 'end': '202609160000'},
            {'mode': '1', 'page': 1, 'start': '202609170000', 'end': '202609160000'},
            {'mode': '1', 'page': 1, 'start': 'invalid', 'end': '202609160000'},
        ]
        async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
            for state in invalid:
                with self.subTest(state=state), self.assertRaises(ValueError):
                    await KonepsSourceAdapter(service_key='synthetic', client=client).discover(
                        json.dumps(state))
        self.assertEqual(calls, [])

    async def test_invalid_lookup_id_is_rejected_before_network(self) -> None:
        calls = []
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=fixture())
        async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
            for key in ('services:bad/id:000', 'services:123:1', 'wrong:123:000'):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    adapter = KonepsSourceAdapter(service_key='synthetic', client=client)
                    await adapter.fetch_record(key)
        self.assertEqual(calls, [])

    async def test_malformed_envelope_returns_safe_value_error(self) -> None:
        for body in ([], {'response': []}, {'response': {'header': []}}, {'error': 'private'}):
            with self.subTest(body=body):
                async with ResilientHttpClient(transport=httpx.MockTransport(
                    lambda r, b=body: httpx.Response(200, json=b)
                )) as client:
                    with self.assertRaises(ValueError):
                        adapter = KonepsSourceAdapter(service_key='synthetic', client=client)
                        await adapter.discover(None)

    async def test_transport_exception_does_not_echo_key(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('failed '+str(request.url), request=request)
        async with ResilientHttpClient(transport=httpx.MockTransport(handler),
                                       max_attempts=1) as client:
            with self.assertRaises(httpx.ConnectError) as caught:
                adapter = KonepsSourceAdapter(
                    service_key='synthetic-private-value', client=client
                )
                await adapter.discover(None)
        self.assertNotIn('synthetic-private-value', str(caught.exception))

    async def test_registration_then_change_window_and_raw_preservation(self) -> None:
        calls = []
        original = fixture()
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=original)
        async with ResilientHttpClient(transport=httpx.MockTransport(handler)) as client:
            adapter = KonepsSourceAdapter(service_key='synthetic+key=', client=client)
            first = await adapter.discover(None)
            second = await adapter.discover(first.next_cursor)
        self.assertEqual([r.url.params['inqryDiv'] for r in calls], ['1', '3'])
        self.assertEqual(calls[0].url.params['inqryBgnDt'], calls[1].url.params['inqryBgnDt'])
        self.assertEqual(calls[0].url.params['serviceKey'], 'synthetic+key=')
        self.assertEqual(first.records[0].raw_payload, original['response']['body']['items'][0])
        self.assertEqual(json.loads(second.next_cursor or '{}')['mode'], 'done')

    async def test_empty_consistent_page_is_valid(self) -> None:
        body = fixture()
        body['response']['body'].update(totalCount=0, items='')
        async with ResilientHttpClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=body)
        )) as client:
            adapter = KonepsSourceAdapter(service_key='synthetic', client=client)
            result = await adapter.discover(None)
        self.assertEqual(result.records, ())

    async def test_retry_transient_only_and_no_response_key_in_error(self) -> None:
        for status, expected in ((401, 1), (503, 3)):
            calls = []

            def handler(
                request: httpx.Request,
                bound_calls: list[httpx.Request] = calls,
                bound_status: int = status,
            ) -> httpx.Response:
                bound_calls.append(request)
                return httpx.Response(bound_status, text='synthetic-private-value')
            async with ResilientHttpClient(transport=httpx.MockTransport(handler),
                                           backoff_base_seconds=0) as client:
                with self.assertRaises(httpx.HTTPStatusError) as caught:
                    adapter = KonepsSourceAdapter(
                        service_key='synthetic-private-value', client=client
                    )
                    await adapter.discover(None)
            self.assertEqual(len(calls), expected)
            self.assertNotIn('synthetic-private-value', str(caught.exception))

    def test_mapping_preserves_input_and_unknown_restrictions(self) -> None:
        item = fixture()['response']['body']['items'][0]
        before = copy.deepcopy(item)
        result = map_payload(item, 'services:R26BK99990001:000')
        self.assertEqual(item, before)
        self.assertEqual(result['closes_at'], datetime(2026, 9, 30, 9, tzinfo=UTC))
        self.assertEqual(result['evidence']['estimated_amount'][0]['json_pointer'], '/presmptPrce')
        self.assertNotIn('regions', result['evidence'])
        self.assertNotIn('required_certifications', result['evidence'])

    def test_nonfinite_or_negative_amount_rejected(self) -> None:
        for amount in ('NaN', 'Infinity', '-1'):
            item = fixture()['response']['body']['items'][0]
            item['presmptPrce'] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                map_payload(item, 'services:R26BK99990001:000')

    def test_nonzero_order_does_not_prove_amendment(self) -> None:
        for kind in ('등록공고', '재공고', '취소공고'):
            item = fixture()['response']['body']['items'][0]
            item.update(bidNtceOrd='002', ntceKindNm=kind)
            mapped = map_payload(item, 'services:R26BK99990001:002')
            self.assertEqual(mapped['lifecycle_stage'], 'tender')
