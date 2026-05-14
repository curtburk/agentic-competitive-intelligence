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
    """Shows pipeline connection status."""

    def on_mount(self) -> None:
        self.update("[dim]Checking connection...[/dim]")
        self.check_health()

    def check_health(self) -> None:
        self.run_worker(self._check(), exclusive=True)

    async def _check(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{API_URL}/health")
                data = resp.json()
                model = data.get("model", "unknown")
                self.update(
                    f"[green bold]CONNECTED[/green bold]  "
                    f"Model: [cyan]{model}[/cyan]  "
                    f"API: [cyan]{API_URL}[/cyan]"
                )
        except Exception:
            self.update("[red bold]DISCONNECTED[/red bold]  Cannot reach orchestrator")


class BriefPanel(VerticalScroll):
    """Displays the latest competitive brief."""

    def compose(self) -> ComposeResult:
        yield Markdown("*Loading latest brief...*", id="brief-content")

    def on_mount(self) -> None:
        self.load_brief()

    def load_brief(self) -> None:
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
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
    """Natural language query interface for the wiki."""

    def compose(self) -> ComposeResult:
        yield Label("Ask a question about your competitive landscape:")
        yield Input(
            placeholder="e.g. How does Dell Pro Max GB300 compare to HP ZGX Fury?",
            id="query-input",
        )
        yield Button("Ask", id="query-btn", variant="primary")
        yield VerticalScroll(
            Markdown("*Results will appear here.*", id="query-result"),
            id="query-scroll",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "query-btn":
            self._submit_query()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query-input":
            self._submit_query()

    def _submit_query(self) -> None:
        inp = self.query_one("#query-input", Input)
        question = inp.value.strip()
        if not question:
            return
        md = self.query_one("#query-result", Markdown)
        md.update("*Searching wiki...*")
        self.run_worker(self._run_query(question), exclusive=True)

    async def _run_query(self, question: str) -> None:
        md = self.query_one("#query-result", Markdown)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{API_URL}/query",
                    json={"question": question},
                )
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
    """Enrich a competitor product profile."""

    def compose(self) -> ComposeResult:
        yield Label("Enrich a competitor product profile:")
        yield Horizontal(
            Input(placeholder="Competitor (e.g. Dell)", id="enrich-competitor"),
            Input(placeholder="Product (e.g. Pro Max GB300)", id="enrich-product"),
            id="enrich-row-1",
        )
        yield Horizontal(
            Input(placeholder="Tier: nano or fury", id="enrich-tier", value="nano"),
            Input(placeholder="Product URL (optional)", id="enrich-url"),
            id="enrich-row-2",
        )
        yield Button("Enrich", id="enrich-btn", variant="primary")
        yield VerticalScroll(
            Markdown("*Results will appear here.*", id="enrich-result"),
            id="enrich-scroll",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "enrich-btn":
            self._submit_enrich()

    def _submit_enrich(self) -> None:
        competitor = self.query_one("#enrich-competitor", Input).value.strip()
        product = self.query_one("#enrich-product", Input).value.strip()
        tier = self.query_one("#enrich-tier", Input).value.strip() or "nano"
        url = self.query_one("#enrich-url", Input).value.strip() or None

        if not competitor or not product:
            md = self.query_one("#enrich-result", Markdown)
            md.update("*Competitor and product name are required.*")
            return

        md = self.query_one("#enrich-result", Markdown)
        md.update(f"*Enriching {competitor} {product}... (this takes 1-3 minutes)*")
        self.run_worker(
            self._run_enrich(competitor, product, tier, url),
            exclusive=True,
        )

    async def _run_enrich(
        self, competitor: str, product: str, tier: str, url: str | None
    ) -> None:
        md = self.query_one("#enrich-result", Markdown)
        try:
            payload = {
                "competitor": competitor,
                "product_name": product,
                "product_tier": tier,
            }
            if url:
                payload["url"] = url

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{API_URL}/enrich", json=payload)
                data = resp.json()

                if data.get("status") == "complete":
                    output = (
                        f"## Enrichment Complete\n\n"
                        f"- **Competitor**: {data.get('competitor')}\n"
                        f"- **Product**: {data.get('product_name')}\n"
                        f"- **Sources found**: {data.get('sources_found', 0)}\n"
                        f"- **Specs extracted**: {data.get('specs_extracted', 0)}\n"
                        f"- **Pricing**: {data.get('pricing', 'Unknown')}\n"
                        f"- **Availability**: {data.get('availability', 'Unknown')}\n"
                        f"- **Wiki path**: `{data.get('wiki_path', '')}`\n"
                    )
                else:
                    output = (
                        f"## Enrichment Failed\n\n"
                        f"**Reason**: {data.get('reason', data.get('error', 'Unknown'))}\n"
                    )

                md.update(output)
        except Exception as e:
            md.update(f"*Enrichment failed: {e}*")


class RunPanel(Vertical):
    """Trigger and monitor a full pipeline run."""

    def compose(self) -> ComposeResult:
        yield Label("Full Pipeline Run")
        yield Static(
            "Executes the complete DAG: search all competitors, "
            "fetch articles, analyze, strategize, write brief, update wiki.",
            id="run-description",
        )
        yield Button(
            "Run Full Scan", id="run-btn", variant="warning"
        )
        yield VerticalScroll(
            RichLog(highlight=True, markup=True, id="run-log"),
            id="run-scroll",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            self._trigger_run()

    def _trigger_run(self) -> None:
        log = self.query_one("#run-log", RichLog)
        btn = self.query_one("#run-btn", Button)
        btn.disabled = True
        btn.label = "Running..."
        log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Starting pipeline run...")
        self.run_worker(self._run_pipeline(), exclusive=True)

    async def _run_pipeline(self) -> None:
        log = self.query_one("#run-log", RichLog)
        btn = self.query_one("#run-btn", Button)

        try:
            log.write(
                f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] "
                f"Executing 52 searches + LLM pipeline. This takes several minutes..."
            )

            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(f"{API_URL}/run")
                data = resp.json()

            status = data.get("status", "unknown")
            run_id = data.get("run_id", "unknown")
            nodes = data.get("nodes_completed", [])

            if status == "complete":
                log.write(
                    f"[green bold]{datetime.now().strftime('%H:%M:%S')} "
                    f"COMPLETE[/green bold] run_id={run_id}"
                )
                log.write(f"  Nodes: {' -> '.join(nodes)}")

                # Fetch and display traces
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
                                log.write(
                                    f"  [{node:12s}] {latency:>6s}s | "
                                    f"in:{inp:>5} out:{out:>5} | "
                                    f"tools:{tools:>3} | {valid_str}"
                                )
                except Exception:
                    pass

                # Refresh the brief panel
                app = self.app
                try:
                    brief_panel = app.query_one("BriefPanel")
                    brief_panel.load_brief()
                    log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Brief panel refreshed.")
                except Exception:
                    pass

            elif status == "partial":
                log.write(
                    f"[yellow bold]{datetime.now().strftime('%H:%M:%S')} "
                    f"PARTIAL[/yellow bold] run_id={run_id}"
                )
                log.write(f"  Nodes completed: {', '.join(nodes)}")
                log.write(f"  Reason: {data.get('reason', 'unknown')}")

            elif status == "aborted":
                log.write(
                    f"[red bold]{datetime.now().strftime('%H:%M:%S')} "
                    f"ABORTED[/red bold] run_id={run_id}"
                )
                log.write(f"  Reason: {data.get('reason', 'unknown')}")

            else:
                log.write(f"[red]Unexpected status: {status}[/red]")
                log.write(f"  Full response: {data}")

        except httpx.ReadTimeout:
            log.write(
                f"[red]{datetime.now().strftime('%H:%M:%S')} "
                f"TIMEOUT[/red] Pipeline took longer than 10 minutes."
            )
        except Exception as e:
            log.write(
                f"[red]{datetime.now().strftime('%H:%M:%S')} "
                f"ERROR[/red] {type(e).__name__}: {e}"
            )
        finally:
            btn.disabled = False
            btn.label = "Run Full Scan"


class CompetitiveIntelApp(App):
    """HP ZGX Competitive Intelligence Dashboard"""

    CSS = """
    Screen {
        background: $surface;
    }

    StatusBar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $boost;
    }

    #enrich-row-1, #enrich-row-2 {
        height: 3;
    }

    #enrich-row-1 Input, #enrich-row-2 Input {
        width: 1fr;
    }

    BriefPanel {
        padding: 1;
    }

    QueryPanel {
        padding: 1;
    }

    QueryPanel Label {
        padding: 0 0 1 0;
    }

    QueryPanel Input {
        margin: 0 0 1 0;
    }

    #query-scroll {
        height: 1fr;
    }

    EnrichPanel {
        padding: 1;
    }

    EnrichPanel Label {
        padding: 0 0 1 0;
    }

    #enrich-scroll {
        height: 1fr;
    }

    RunPanel {
        padding: 1;
    }

    RunPanel Label {
        padding: 0 0 1 0;
    }

    #run-description {
        color: $text-muted;
        margin: 0 0 1 0;
    }

    #run-scroll {
        height: 1fr;
    }
    """

    TITLE = "HP ZGX Competitive Intelligence"
    SUB_TITLE = "Compliance by Architecture"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_brief", "Brief", show=True),
        Binding("2", "tab_query", "Query", show=True),
        Binding("3", "tab_enrich", "Enrich", show=True),
        Binding("4", "tab_run", "Run", show=True),
    ]

    def compose(self) -> ComposeResult:
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
        yield Footer()

    def action_refresh(self) -> None:
        """Refresh the status bar and current brief."""
        self.query_one(StatusBar).check_health()
        self.query_one(BriefPanel).load_brief()

    def action_tab_brief(self) -> None:
        self.query_one(TabbedContent).active = "brief"

    def action_tab_query(self) -> None:
        self.query_one(TabbedContent).active = "query"

    def action_tab_enrich(self) -> None:
        self.query_one(TabbedContent).active = "enrich"

    def action_tab_run(self) -> None:
        self.query_one(TabbedContent).active = "run"


if __name__ == "__main__":
    app = CompetitiveIntelApp()
    app.run()