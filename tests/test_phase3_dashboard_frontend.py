"""Focused checks for the framework-free Phase 3 analytics page renderers."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ANALYTICS_JS = FRONTEND / "analytics.js"
ANALYTICS_HTML = FRONTEND / "analytics.html"
NODE = shutil.which("node")


class _AssetParser(HTMLParser):
    """Collect page asset URLs while ignoring SVG namespace declarations."""

    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href"} and value:
                self.assets.append(value)


@unittest.skipUnless(NODE, "Node.js is required for analytics renderer checks")
class AnalyticsDashboardFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.javascript = ANALYTICS_JS.read_text(encoding="utf-8")
        cls.html = ANALYTICS_HTML.read_text(encoding="utf-8")

    def run_node(self, source):
        completed = subprocess.run(
            [NODE, "-e", source],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"Node check failed:\n{completed.stdout}\n{completed.stderr}",
        )

    def test_javascript_syntax(self):
        completed = subprocess.run(
            [NODE, "--check", str(ANALYTICS_JS)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_page_has_controls_backlink_and_existing_local_assets(self):
        parser = _AssetParser()
        parser.feed(self.html)
        required_ids = {
            "analyticsSession",
            "analyticsRefresh",
            "analyticsMessage",
            "sessionContext",
            "overviewCards",
            "analyticsCharts",
            "analyticsTables",
        }
        found_ids = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertTrue(required_ids.issubset(found_ids))
        self.assertRegex(self.html, r'<a\b[^>]*href="/index\.html"[^>]*>Back to Chat</a>')

        for asset in parser.assets:
            parsed = urlsplit(asset)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                continue
            local_path = FRONTEND / parsed.path.lstrip("/")
            self.assertTrue(local_path.is_file(), f"Missing local page asset: {asset}")

    def test_runtime_uses_text_rendering_and_read_only_local_storage(self):
        self.assertIsNone(re.search(r"\.innerHTML\s*=", self.javascript))
        self.assertIsNone(
            re.search(r"localStorage\s*\.\s*(?:setItem|removeItem|clear)\s*\(", self.javascript)
        )
        self.assertIsNone(re.search(r"localStorage\s*\[[^]]+\]\s*=", self.javascript))

    def test_helpers_distinguish_missing_and_measured_zero_and_choose_session(self):
        self.run_node(
            r"""
            const assert = require('node:assert/strict');
            const api = require('./frontend/analytics.js');
            assert.equal(api.displayValue(null, 'percent'), 'N/A');
            assert.equal(api.displayValue(0, 'percent'), '0%');
            assert.equal(api.displayValue(0.004, 'seconds'), '0.004 s');
            const sessions = [
              {session_id: 'older', updated_at: '2026-01-01T00:00:00Z'},
              {session_id: 'preferred', updated_at: '2025-01-01T00:00:00Z'},
              {session_id: 'current', updated_at: '2026-02-01T00:00:00Z'}
            ];
            assert.equal(api.chooseSession(sessions, 'preferred', null), 'preferred');
            assert.equal(api.chooseSession(sessions, 'preferred', 'current'), 'current');
            assert.equal(api.chooseSession(sessions, 'not-owned', 'current'), 'current');
            assert.equal(api.chooseSession(sessions, 'not-owned', null), 'current');
            assert.equal(api.chooseSession([
              {session_id: 'zeta', updated_at: '2026-04-01T00:00:00Z'},
              {session_id: 'alpha', updated_at: '2026-04-01T00:00:00Z'}
            ], null, null), 'alpha');
            const timezoneSessions = [
              {session_id: 'newer-naive', updated_at: '2026-10-10T10:00:00'},
              {session_id: 'older-aware', updated_at: '2026-10-10T09:30:00Z'}
            ];
            const originalTimezone = process.env.TZ;
            process.env.TZ = 'Asia/Karachi';
            const karachiChoice = api.chooseSession(timezoneSessions, null, null);
            process.env.TZ = 'UTC';
            const utcChoice = api.chooseSession(timezoneSessions, null, null);
            if (originalTimezone === undefined) delete process.env.TZ;
            else process.env.TZ = originalTimezone;
            assert.equal(karachiChoice, 'newer-naive');
            assert.equal(utcChoice, karachiChoice);
            assert.equal(api.chooseSession([], null, null), null);
            const maximum = api.axisMaximum({}, [1.5e308]);
            assert(Number.isFinite(maximum));
            assert(maximum >= 1.5e308);
            """
        )

    def test_table_uses_arbitrary_columns_and_text_nodes_for_untrusted_values(self):
        self.run_node(
            r"""
            const assert = require('node:assert/strict');
            const api = require('./frontend/analytics.js');
            function makeNode(tag, namespace) {
              const node = {
                tagName: tag, namespaceURI: namespace, children: [], attributes: {}, style: {},
                className: '', tabIndex: 0, _text: '',
                appendChild(child) { this.children.push(child); return child; },
                append(...children) { children.forEach(child => this.appendChild(child)); },
                setAttribute(key, value) { this.attributes[key] = String(value); }
              };
              Object.defineProperty(node, 'textContent', {
                get() { return this._text + this.children.map(child => child.textContent || '').join(''); },
                set(value) { this._text = String(value); }
              });
              Object.defineProperty(node, 'innerHTML', {
                set() { throw new Error('innerHTML must never be assigned'); },
                get() { return undefined; }
              });
              return node;
            }
            global.document = {
              createElement: tag => makeNode(tag, null),
              createElementNS: (namespace, tag) => makeNode(tag, namespace),
              createTextNode: value => { const node = makeNode('#text', null); node.textContent = value; return node; }
            };
            const malicious = '<img src=x onerror=alert(1)>';
            const first = api.renderTable({
              title: 'Arbitrary table',
              columns: [{key: 'custom_metric', label: 'Custom label'}, {key: 'detail', label: 'Details'}],
              rows: [{custom_metric: 0, detail: malicious}, {custom_metric: null, detail: ''}],
              valid_response_count: 2
            });
            const second = api.renderTable({title: 'Fresh result', columns: [], rows: []});
            assert.notEqual(first, second);
            assert.equal(first.children[0].textContent, 'Arbitrary table');
            const walk = (node, out = []) => { out.push(node); node.children.forEach(child => walk(child, out)); return out; };
            const nodes = walk(first);
            assert(nodes.some(node => node.tagName === 'th' && node.textContent === 'Custom label'));
            assert(nodes.some(node => node.tagName === 'td' && node.textContent === '0'));
            assert(nodes.some(node => node.tagName === 'td' && node.textContent === malicious));
            assert.equal(nodes.filter(node => node.tagName === 'td' && node.textContent === 'N/A').length, 2);
            assert(nodes.some(node => node.textContent === '2 timed replies'));
            assert.equal(nodes.some(node => node.tagName === 'img' || node.tagName === 'script'), false);
            """
        )

    def test_svg_charts_keep_missing_values_and_numeric_attributes_finite(self):
        self.run_node(
            r"""
            const assert = require('node:assert/strict');
            const api = require('./frontend/analytics.js');
            function makeNode(tag, namespace) {
              const node = {
                tagName: tag, namespaceURI: namespace, children: [], attributes: {}, style: {}, _text: '',
                appendChild(child) { this.children.push(child); return child; },
                append(...children) { children.forEach(child => this.appendChild(child)); },
                setAttribute(key, value) { this.attributes[key] = String(value); }
              };
              Object.defineProperty(node, 'textContent', {
                get() { return this._text + this.children.map(child => child.textContent || '').join(''); },
                set(value) { this._text = String(value); }
              });
              Object.defineProperty(node, 'innerHTML', {
                set() { throw new Error('innerHTML must never be assigned'); },
                get() { return undefined; }
              });
              return node;
            }
            global.document = {
              createElement: tag => makeNode(tag, null),
              createElementNS: (namespace, tag) => makeNode(tag, namespace),
              createTextNode: value => { const node = makeNode('#text', null); node.textContent = value; return node; }
            };
            const walk = (node, out = []) => { out.push(node); node.children.forEach(child => walk(child, out)); return out; };
            const finiteAttrs = new Set(['x','y','x1','x2','y1','y2','cx','cy','r','width','height','rx','stroke-width','stroke-opacity']);
            const checkFinite = nodes => nodes.forEach(node => Object.entries(node.attributes).forEach(([key, value]) => {
              if (finiteAttrs.has(key)) assert(Number.isFinite(Number(value)), `${key}=${value}`);
            }));

            const bars = api.renderBarChart({
              title: 'Bars', labels: ['Zero', 'Missing', 'Measured'],
              datasets: [{values: [0, null, 50]}], metadata: {unit: 'percent'}
            });
            const barNodes = walk(bars);
            assert.equal(barNodes.filter(node => node.tagName === 'rect').length, 2);
            assert(barNodes.some(node => node.textContent === 'N/A'));
            assert(barNodes.some(node => node.textContent === '0%'));
            checkFinite(barNodes);

            const line = api.renderLineChart({
              title: 'Line', labels: ['A', 'Gap', 'C', 'D'],
              datasets: [{values: [10, null, 30, 40]}], metadata: {unit: 'seconds'}
            });
            const lineNodes = walk(line);
            assert.equal(lineNodes.filter(node => node.tagName === 'circle').length, 3);
            const polylines = lineNodes.filter(node => node.tagName === 'polyline');
            assert.equal(polylines.length, 1);
            assert.equal(polylines[0].attributes.points.trim().split(/\s+/).length, 2);
            assert(lineNodes.some(node => node.textContent === 'N/A'));
            checkFinite(lineNodes);

            const emptyPie = api.renderPieChart({labels: ['Zero'], datasets: [{values: [0]}]});
            const emptyNodes = walk(emptyPie);
            assert.equal(emptyNodes.filter(node => node.tagName === 'path').length, 0);
            assert(emptyNodes.every(node => !Object.values(node.attributes).some(value => /NaN|Infinity/.test(value))));
            checkFinite(emptyNodes);

            const pie = api.renderPieChart({
              title: 'Pie', labels: ['Small', 'Large'], datasets: [{values: [1, 3]}],
              metadata: {percentages: [12.34, 87.66], total_count: 4}
            });
            const pieNodes = walk(pie);
            const paths = pieNodes.filter(node => node.tagName === 'path');
            assert.equal(paths.length, 2);
            assert(paths[0].children.some(node => node.tagName === 'title' && node.textContent === 'Small: 1 (12.34%)'));
            assert(paths[1].children.some(node => node.tagName === 'title' && node.textContent === 'Large: 3 (87.66%)'));
            assert.match(paths[0].attributes.d, / 0 0 1 /);
            assert.match(paths[1].attributes.d, / 0 1 1 /);
            checkFinite(pieNodes);

            const single = api.renderPieChart({labels: ['Only'], datasets: [{values: [5]}]});
            assert.equal(walk(single).filter(node => node.tagName === 'path').length, 0);
            assert.equal(walk(single).filter(node => node.tagName === 'circle').length, 2);
            assert.notEqual(bars, api.renderBarChart({labels: ['Again'], datasets: [{values: [1]}]}));
            """
        )


if __name__ == "__main__":
    unittest.main()
