"""
ci.py - Competitive Intelligence TUI
A terminal dashboard for the competitive intelligence pipeline.
Run from the Nano: python3 ci.py
"""

import asyncio
import httpx
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, Input, Button, TabbedContent,
    TabPane, RichLog, Label, LoadingIndicator, Markdown,
)
from textual.binding import Binding
from textual.worker import Worker, get_current_worker

API_URL = "http://localhost:8000"


class StatusBar(Static):
    def on_mount(self):
        self.update("[dim]Checking connection...[/dim]")
        self.check_health()
    def check_health(self):
        self.run_worker(self._check(), exclusive=True)
    async def _check(self):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{API_URL}/health")
                data = resp.json()
                model = data.get("model", "unknown")
                self.update(f"[green bold]CONNECTED[/green bold]  Model: [cyan]{model}[/cyan]  API: [cyan]{API_URL}[/cyan]")
        except Exception:
            self.update("[red bold]DISCONNECTED[/red bold]  Cannot reach orchestrator")


class BriefPanel(VerticalScroll):
    def compose(self):
        yield Markdown("*Loading latest brief...*", id="brief-content")
    def on_mount(self):
        self.load_brief()
    def load_brief(self):
        self.run_worker(self._load(), exclusive=True)
    async def _load(self):
        md = self.query_one("#brief-content", Markdown)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{API_URL}/latest")
                data = resp.json()
                if "brief" in data:
                    md.update(data["brief"])
                else:
                    md.update("*No briefs yet. Run a scan first.*")
        except Exception as e:
            md.update(f"*Error loading brief: {e}*")


class QueryPanel(Vertical):
    def compose(self):
        yield Label("Ask a question about your competitive landscape:")
        yield Input(placeholder="e.g. How does Dell Pro Max GB300 compare to HP ZGX Fury?", id="query-input")
        yield Button("Ask", id="query-btn", variant="primary")
        yield VerticalScroll(Markdown("*Results will appear here.*", id="query-result"), id="query-scroll")
    def on_button_pressed(self, event):
        if event.button.id == "query-btn":
            self._submit_query()
    def on_input_submitted(self, event):
        if event.input.id == "query-input":
            self._submit_query()
    def _submit_query(self):
        inp = self.query_one("#query-input", Input)
        question = inp.value.strip()
        if not question:
            return
        md = self.query_one("#query-result", Markdown)
        md.update("*Searching wiki...*")
        self.run_worker(self._run_query(question), exclusive=True)
    async def _run_query(self, question):
        md = self.query_one("#query-result", Markdown)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{API_URL}/query", json={"question": question})
                data = resp.json()
                if "error" in data:
                    md.update(f"*Error: {data['error']}*")
                    return
                answer = data.get("answer", "No answer returned.")
                sources = data.get("sources", [])
                output = f"{answer}\n\n---\n\n**Sources:**\n"
                for s in sources[:5]:
                    output += f"- `{s['path']}` (score: {s['score']})\n"
                md.update(output)
        except Exception as e:
            md.update(f"*Query failed: {e}*")


class EnrichPanel(Vertical):
    def compose(self):
        yield Label("Enrich a competitor product profile:")
        yield Horizontal(
            Input(placeholder="Competitor (e.g. Dell)", id="enrich-competitor"),
            Input(placeholder="Product (e.g. Pro Max GB300)", id="enrich-product"),
            id="enrich-row-1")
        yield Horizontal(
            Input(placeholder="Tier: nano or fury", id="enrich-tier", value="nano"),
            Input(placeholder="Product URL (optional)", id="enrich-url"),
            id="enrich-row-2")
        yield Button("Enrich", id="enrich-btn", variant="primary")
        yield VerticalScroll(Markdown("*Results will appear here.*", id="enrich-result"), id="enrich-scroll")
    def on_button_pressed(self, event):
        if event.button.id == "enrich-btn":
            self._submit_enrich()
    def _submit_enrich(self):
        competitor = self.query_one("#enrich-competitor", Input).value.strip()
        product = self.query_one("#enrich-product", Input).value.strip()
        tier = self.query_one("#enrich-tier", Input).value.strip() or "nano"
        url = self.query_one("#enrich-url", Input).value.strip() or None
        if not competitor or not product:
            self.query_one("#enrich-result", Markdown).update("*Competitor and product name are required.*")
            return
        self.query_one("#enrich-result", Markdown).update(f"*Enriching {competitor} {product}... (1-3 minutes)*")
        self.run_worker(self._run_enrich(competitor, product, tier, url), exclusive=True)
    async def _run_enrich(self, competitor, product, tier, url):
        md = self.query_one("#enrich-result", Markdown)
        try:
            payload = {"competitor": competitor, "product_name": product, "product_tier": tier}
            if url:
                payload["url"] = url
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{API_URL}/enrich", json=payload)
                data = resp.json()
                if data.get("status") == "complete":
                    output = (f"## Enrichment Complete\n\n"
                        f"- **Competitor**: {data.get('competitor')}\n"
                        f"- **Product**: {data.get('product_name')}\n"
                        f"- **Sources found**: {data.get('sources_found', 0)}\n"
                        f"- **Specs extracted**: {data.get('specs_extracted', 0)}\n"
                        f"- **Pricing**: {data.get('pricing', 'Unknown')}\n"
                        f"- **Availability**: {data.get('availability', 'Unknown')}\n"
                        f"- **Wiki path**: `{data.get('wiki_path', '')}`\n")
                else:
                    output = f"## Enrichment Failed\n\n**Reason**: {data.get('reason', data.get('error', 'Unknown'))}\n"
                md.update(output)
        except Exception as e:
            md.update(f"*Enrichment failed: {e}*")


class RunPanel(Vertical):
    def compose(self):
        yield Label("Full Pipeline Run")
        yield Static("Executes the complete DAG: search all competitors, fetch articles, analyze, strategize, write brief, update wiki.", id="run-description")
        yield Button("Run Full Scan", id="run-btn", variant="warning")
        yield VerticalScroll(RichLog(highlight=True, markup=True, id="run-log"), id="run-scroll")
    def on_button_pressed(self, event):
        if event.button.id == "run-btn":
            self._trigger_run()
    def _trigger_run(self):
        log = self.query_one("#run-log", RichLog)
        btn = self.query_one("#run-btn", Button)
        btn.disabled = True
        btn.label = "Running..."
        log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Starting pipeline run...")
        self.run_worker(self._run_pipeline(), exclusive=True)
    async def _run_pipeline(self):
        log = self.query_one("#run-log", RichLog)
        btn = self.query_one("#run-btn", Button)
        try:
            log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Executing 52 searches + LLM pipeline. This takes several minutes...")
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(f"{API_URL}/run")
                data = resp.json()
            status = data.get("status", "unknown")
            run_id = data.get("run_id", "unknown")
            nodes = data.get("nodes_completed", [])
            if status == "complete":
                log.write(f"[green bold]{datetime.now().strftime('%H:%M:%S')} COMPLETE[/green bold] run_id={run_id}")
                log.write(f"  Nodes: {' -> '.join(nodes)}")
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        trace_resp = await client.get(f"{API_URL}/traces/{run_id}")
                        traces = trace_resp.json()
                        if isinstance(traces, list):
                            for t in traces:
                                node = t.get("node", "?")
                                latency = t.get("latency_seconds", "?")
                                inp = t.get("input_tokens", 0)
                                out = t.get("output_tokens", 0)
                                tools = len(t.get("tool_calls", []))
                                valid = t.get("validation_passed", False)
                                valid_str = "[green]PASS[/green]" if valid else "[red]FAIL[/red]"
                                log.write(f"  [{node:12s}] {latency:>6s}s | in:{inp:>5} out:{out:>5} | tools:{tools:>3} | {valid_str}")
                except Exception:
                    pass
                try:
                    self.app.query_one("BriefPanel").load_brief()
                    log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Brief panel refreshed.")
                except Exception:
                    pass
            elif status == "partial":
                log.write(f"[yellow bold]{datetime.now().strftime('%H:%M:%S')} PARTIAL[/yellow bold] run_id={run_id}")
                log.write(f"  Nodes completed: {', '.join(nodes)}")
                log.write(f"  Reason: {data.get('reason', 'unknown')}")
            elif status == "aborted":
                log.write(f"[red bold]{datetime.now().strftime('%H:%M:%S')} ABORTED[/red bold] run_id={run_id}")
                log.write(f"  Reason: {data.get('reason', 'unknown')}")
            else:
                log.write(f"[red]Unexpected status: {status}[/red]")
                log.write(f"  Full response: {data}")
        except httpx.ReadTimeout:
            log.write(f"[red]{datetime.now().strftime('%H:%M:%S')} TIMEOUT[/red] Pipeline took longer than 10 minutes.")
        except Exception as e:
            log.write(f"[red]{datetime.now().strftime('%H:%M:%S')} ERROR[/red] {type(e).__name__}: {e}")
        finally:
            btn.disabled = False
            btn.label = "Run Full Scan"


class StrategyPanel(Vertical):
    """Standalone strategy assessment for individual competitors."""
    def compose(self):
        yield Label("Competitor Strategy Assessment:")
        yield Input(placeholder="Competitor name (e.g. dell, amd, lenovo)", id="strategy-input")
        yield Horizontal(
            Button("Assess One", id="strategy-one-btn", variant="primary"),
            Button("Assess All", id="strategy-all-btn", variant="warning"),
            id="strategy-buttons")
        yield VerticalScroll(
            Markdown("*Select a competitor and click Assess, or click Assess All.*", id="strategy-result"),
            id="strategy-scroll")
    def on_button_pressed(self, event):
        if event.button.id == "strategy-one-btn":
            self._assess_one()
        elif event.button.id == "strategy-all-btn":
            self._assess_all()
    def on_input_submitted(self, event):
        if event.input.id == "strategy-input":
            self._assess_one()
    def _assess_one(self):
        inp = self.query_one("#strategy-input", Input)
        competitor = inp.value.strip()
        if not competitor:
            self.query_one("#strategy-result", Markdown).update("*Enter a competitor name first.*")
            return
        self.query_one("#strategy-result", Markdown).update(f"*Assessing {competitor}... (loading wiki data + LLM call, 1-3 min)*")
        self.run_worker(self._run_assess(competitor), exclusive=True)
    def _assess_all(self):
        self.query_one("#strategy-result", Markdown).update("*Assessing ALL competitors... This will take several minutes.*")
        self.run_worker(self._run_assess_all(), exclusive=True)
    async def _run_assess(self, competitor):
        md = self.query_one("#strategy-result", Markdown)
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{API_URL}/strategy", json={"competitor": competitor})
                data = resp.json()
                if data.get("status") == "complete":
                    output = (f"## {competitor.title()} Strategy Assessment\n\n"
                        f"**Findings analyzed**: {data.get('findings_count', 0)}\n"
                        f"**Tokens**: {data.get('input_tokens', 0)} in / {data.get('output_tokens', 0)} out\n"
                        f"**Saved to**: `{data.get('wiki_path', '')}`\n\n---\n\n"
                        f"{data.get('assessment', 'No assessment produced.')}\n")
                elif "error" in data:
                    output = f"**Error**: {data['error']}"
                else:
                    output = f"## Assessment Failed\n\n**Reason**: {data.get('reason', 'Unknown')}\n"
                md.update(output)
        except Exception as e:
            md.update(f"*Strategy assessment failed: {e}*")
    async def _run_assess_all(self):
        md = self.query_one("#strategy-result", Markdown)
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(f"{API_URL}/strategy/all")
                data = resp.json()
                if data.get("status") == "complete":
                    competitors = data.get("competitors", {})
                    output = "## All Competitor Strategies\n\n"
                    for name, info in competitors.items():
                        status = info.get("status", "unknown")
                        icon = "+" if status == "complete" else "x"
                        findings = info.get("findings_count", 0)
                        tokens = info.get("output_tokens", 0)
                        output += f"- [{icon}] **{name}**: {findings} findings, {tokens} tokens ({status})\n"
                    output += "\n*Strategy files written to `data/wiki/positioning/strategy-*.md`*"
                else:
                    output = f"**Failed**: {data.get('reason', 'Unknown')}"
                md.update(output)
        except Exception as e:
            md.update(f"*Strategy assessment failed: {e}*")


class CompetitiveIntelApp(App):
    """HP ZGX Competitive Intelligence Dashboard"""
    CSS = """
    Screen { background: $surface; }
    StatusBar { dock: top; height: 1; padding: 0 1; background: $boost; }
    #enrich-row-1, #enrich-row-2 { height: 3; }
    #enrich-row-1 Input, #enrich-row-2 Input { width: 1fr; }
    BriefPanel { padding: 1; }
    QueryPanel { padding: 1; }
    QueryPanel Label { padding: 0 0 1 0; }
    QueryPanel Input { margin: 0 0 1 0; }
    #query-scroll { height: 1fr; }
    EnrichPanel { padding: 1; }
    EnrichPanel Label { padding: 0 0 1 0; }
    #enrich-scroll { height: 1fr; }
    RunPanel { padding: 1; }
    RunPanel Label { padding: 0 0 1 0; }
    #run-description { color: $text-muted; margin: 0 0 1 0; }
    #run-scroll { height: 1fr; }
    StrategyPanel { padding: 1; }
    StrategyPanel Label { padding: 0 0 1 0; }
    #strategy-buttons { height: 3; }
    #strategy-scroll { height: 1fr; }
    """
    TITLE = "HP ZGX Competitive Intelligence"
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_brief", "Brief", show=True),
        Binding("2", "tab_query", "Query", show=True),
        Binding("3", "tab_enrich", "Enrich", show=True),
        Binding("4", "tab_run", "Run", show=True),
        Binding("5", "tab_strategy", "Strategy", show=True),
    ]
    def compose(self):
        yield Header()
        yield StatusBar()
        with TabbedContent(initial="brief"):
            with TabPane("Latest Brief", id="brief"):
                yield BriefPanel()
            with TabPane("Query Wiki", id="query"):
                yield QueryPanel()
            with TabPane("Enrich Product", id="enrich"):
                yield EnrichPanel()
            with TabPane("Run Pipeline", id="run"):
                yield RunPanel()
            with TabPane("Strategy", id="strategy"):
                yield StrategyPanel()
        yield Footer()
    def action_refresh(self):
        self.query_one(StatusBar).check_health()
        self.query_one(BriefPanel).load_brief()
    def action_tab_brief(self):
        self.query_one(TabbedContent).active = "brief"
    def action_tab_query(self):
        self.query_one(TabbedContent).active = "query"
    def action_tab_enrich(self):
        self.query_one(TabbedContent).active = "enrich"
    def action_tab_run(self):
        self.query_one(TabbedContent).active = "run"
    def action_tab_strategy(self):
        self.query_one(TabbedContent).active = "strategy"

if __name__ == "__main__":
    app = CompetitiveIntelApp()
    app.run()