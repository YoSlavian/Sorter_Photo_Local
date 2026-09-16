"""Rule-based parser turning a free-form process description into IR.

Design notes
------------
The parser is a **single left-to-right pass over statements with a frame
stack**.  Each frame corresponds to an open structural block (a decision or a
parallel split); a statement either extends the top frame, descends into it, or
closes it.  There is no backtracking, which makes the behaviour predictable and
every decision explainable in a diagnostic message.

Nesting is recovered from two independent signals that real documents use
interchangeably:

* **indentation / list ordinals** — ``2.1`` under ``2`` is a nested step;
* **discourse cues** — "иначе" opens an alternative arm, "после этого" closes
  the block and merges the flow.

Where the two disagree the cue wins, because cues are explicit while
indentation is often lost in copy-paste.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from bpmn_architect.domain.ir import (
    BranchType,
    EventPosition,
    EventTrigger,
    IRActivity,
    IRArm,
    IRBranch,
    IRElement,
    IREvent,
    IRGoto,
    IRParallel,
    IRProcess,
    IRSequence,
    walk,
)
from bpmn_architect.parsing import lexicon as lex
from bpmn_architect.parsing.morphology import (
    capitalize_first,
    from_genitive,
    looks_like_infinitive,
    looks_like_verb,
    nominalize,
    normalize_actor,
    to_nominative_object,
)
from bpmn_architect.parsing.morphology import to_infinitive as _to_infinitive
from bpmn_architect.parsing.normalizer import Line, clean_label, read_lines, split_sentences

__all__ = ["NaturalLanguageParser", "ParserOptions", "parse_text"]


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ParserOptions:
    """Knobs that change *style*, never correctness."""

    #: Rewrite "менеджер проверяет заявку" as "Проверить заявку".
    infinitive_names: bool = True
    #: Derive swimlanes from the detected actors.
    detect_lanes: bool = True
    #: Split "проверяет заявку и передаёт её в бухгалтерию" into two tasks.
    split_conjoined_actions: bool = True
    #: Carry the actor of the previous step over to steps that do not name one.
    inherit_actor: bool = True
    #: Forced language ("ru"/"en"); auto-detected when ``None``.
    language: str | None = None


# --------------------------------------------------------------------------- #
# Internal statement / frame model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Statement:
    text: str
    indent: int
    line: int
    listed: bool


@dataclass(slots=True)
class _Frame:
    """An open structural block."""

    sequence: IRSequence
    open_indent: int
    kind: str = "root"  # root | branch | parallel
    branch: IRBranch | None = None
    parallel: IRParallel | None = None
    body_indent: int | None = None
    actor: str | None = None


_ARM_LABELS = {
    "ru": ("Да", "Нет"),
    "en": ("Yes", "No"),
}
_DEFAULT_NAMES = {
    "ru": {"start": "Начало процесса", "end": "Конец процесса"},
    "en": {"start": "Process start", "end": "Process end"},
}

_ELSE_SPLIT_RE = re.compile(
    r",?\s*(?:иначе|в\s+противном\s+случае|если\s+нет|otherwise|else|if\s+not)\b[\s:,\-—–]*",
    re.IGNORECASE,
)
_THEN_SPLIT_RE = re.compile(r",\s*(?:то|тогда)\s+|\s+then\s+|\s+—\s+|\s+–\s+|\s*→\s*", re.IGNORECASE)
_CONJUNCTION_SPLIT_RE = re.compile(
    r",?\s+(?:а\s+)?(?:затем|потом|после\s+чего|далее|и|then|and|after\s+which)\s+", re.IGNORECASE
)
#: Start cues that leave their payload in the genitive case.
_GENITIVE_CUE_RE = re.compile(r"(?:\bс|\bсо|\bот|\bиз)\s*$", re.IGNORECASE)
_TITLE_PREFIX_RE = re.compile(
    r"^(?:процесс|название\s+процесса|бизнес-процесс|process|process\s+name)\s*[:—–-]\s*(?P<name>.+)$",
    re.IGNORECASE,
)
_BRACKET_ACTOR_RE = re.compile(r"^\[(?P<actor>[^\]]{1,40})\]\s*(?P<rest>.+)$")
_COLON_ACTOR_RE = re.compile(r"^(?P<actor>[^:;]{2,40}?)\s*:\s*(?P<rest>.{3,})$")
_BY_ACTOR_RE = re.compile(r"\s+by\s+(?:the\s+)?(?P<actor>[A-Za-z][\w\-]*(?:\s+[A-Za-z][\w\-]*){0,2})\s*$", re.IGNORECASE)
_INSTRUMENTAL_ENDINGS = ("ами", "ями", "ом", "ем", "ой", "ей", "ью")
#: Adverbs that may sit between a role and its verb ("система автоматически
#: отправляет"); they are part of the action, never part of the lane name.
_ADVERBS = frozenset(
    {
        "автоматически", "вручную", "самостоятельно", "немедленно", "сразу",
        "обычно", "дополнительно", "предварительно", "повторно", "лично",
        "ежедневно", "периодически", "оперативно", "затем", "также",
        "automatically", "manually", "immediately", "personally", "again",
        "periodically", "also", "then", "usually",
    }
)
_PREPOSITIONS = frozenset(
    {
        "с", "со", "между", "перед", "над", "под", "за", "вместе", "рядом",
        "по", "к", "ко", "от", "ото", "из", "изо", "для", "при", "о", "об",
        "обо", "у", "до", "без", "через", "про", "в", "во", "на",
    }
)
#: Pronouns that stand in for the actor named in an earlier sentence.
_PRONOUN_SUBJECTS = frozenset(
    {"он", "она", "оно", "они", "he", "she", "they", "it"}
)
#: Pronouns in an oblique case: the clause describes something done *to* them,
#: so the actor stays whoever acted last ("ему дается доп. время").
_PRONOUN_OBJECTS = frozenset({"ему", "ей", "им", "ним", "ней", "him", "her", "them"})
#: Impersonal verbs that merely announce that something takes place; the noun
#: phrase after them is the step ("происходит проверка" -> "Проверка").
_IMPERSONAL_VERBS = frozenset(
    {
        "происходит", "происходят", "выполняется", "выполняются", "осуществляется",
        "осуществляются", "производится", "производятся", "проводится", "проводятся",
        "ведется", "ведётся", "идет", "идёт", "начинается", "takes", "occurs", "happens",
    }
)
#: Verb-initial passives ("дается доп. время"): the description never names who
#: acts, so the step is rewritten as the action itself.
_PASSIVE_ACTIONS = {
    "дается": "дать", "даётся": "дать", "предоставляется": "предоставить",
    "выдается": "выдать", "выдаётся": "выдать", "назначается": "назначить",
    "начисляется": "начислить", "формируется": "сформировать",
    "составляется": "составить", "оформляется": "оформить",
    "отправляется": "отправить", "направляется": "направить",
    "рассматривается": "рассмотреть", "регистрируется": "зарегистрировать",
}
#: A parenthetical aside: commentary about the step, never part of its name.
_ASIDE_RE = re.compile(r"\s*\(([^()]*)\)")
#: Verbs saying that something is over, used together with the process name.
_COMPLETION_RE = re.compile(
    r"\b(?:заканчива\w*|оканчива\w*|завершае\w*|заверш[её]н\w*|окончен\w*|прерывае\w*)\b",
    re.IGNORECASE,
)
#: "Бизнес-процесс «Сдача экзамена» начинается ..." names the process itself.
_QUOTED_PROCESS_RE = re.compile(
    r"(?:бизнес-)?процесс\w*\s+\"(?P<name>[^\"]{2,60})\"", re.IGNORECASE
)
#: "начинается с момента входа студента" - "момент" is scaffolding, the event
#: is what follows it.
_MOMENT_LEAD_RE = re.compile(
    r"^(?:того\s+)?момент[аеу]?\s*,?\s*(?:когда\s+|как\s+)?", re.IGNORECASE
)
#: A comma that separates two finite clauses ("тянет билет, называет номер").
_COMMA_SPLIT_RE = re.compile(r",\s+")


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


class NaturalLanguageParser:
    """Turns a natural-language description into an :class:`IRProcess`."""

    def __init__(self, options: ParserOptions | None = None) -> None:
        self.options = options or ParserOptions()
        self.warnings: list[str] = []

    # -- entry point ---------------------------------------------------------

    def parse(self, raw_text: str) -> IRProcess:
        self.warnings = []
        lines = read_lines(raw_text)
        if not lines:
            return IRProcess(name="", root=IRSequence())

        language = self.options.language or lex.detect_language(raw_text)
        process = IRProcess(name="", language=language)
        self._language = language
        self._process = process
        self._last_actor: str | None = None
        self._current_indent = 0

        title, body_lines = self._extract_title(lines)
        process.name = title
        statements = self._to_statements(body_lines)

        self._stack: list[_Frame] = [_Frame(sequence=process.root, open_indent=-1, kind="root")]
        index = 0
        while index < len(statements):
            index = self._dispatch(statements, index)

        self._post_process(process)
        return process

    # -- segmentation --------------------------------------------------------

    def _extract_title(self, lines: list[Line]) -> tuple[str, list[Line]]:
        """Pull an optional heading off the top of the document."""
        first = lines[0]
        if len(lines) < 2:
            return "", lines  # a single line is the process, not its title
        if match := _TITLE_PREFIX_RE.match(first.text):
            candidate = clean_label(match.group("name"))
            if candidate and not lex.match_start(first.text):
                return capitalize_first(candidate), lines[1:]
        if first.is_listed or first.text.endswith((".", "!", "?", ":")):
            return "", lines
        words = first.text.split()
        has_cue = any(
            (
                lex.match_start(first.text),
                lex.match_end(first.text),
                lex.match_condition(first.text),
                lex.match_parallel(first.text),
            )
        )
        describes_an_action = any(
            looks_like_verb(_bare(word)) or looks_like_infinitive(_bare(word)) for word in words
        )
        if not has_cue and 1 <= len(words) <= 8 and not describes_an_action:
            return capitalize_first(clean_label(first.text)), lines[1:]
        return "", lines

    def _to_statements(self, lines: list[Line]) -> list[_Statement]:
        statements: list[_Statement] = []
        for line in lines:
            for sentence in split_sentences(line.text) or [line.text]:
                text = sentence.strip()
                if text:
                    statements.append(
                        _Statement(
                            text=text, indent=line.indent, line=line.number, listed=line.is_listed
                        )
                    )
        return statements

    # -- dispatch ------------------------------------------------------------

    def _dispatch(self, statements: list[_Statement], index: int) -> int:
        stmt = statements[index]
        self._unwind(stmt)
        frame = self._stack[-1]

        # An arm opener extends the enclosing decision instead of adding a step.
        if self._accepts_arm(frame, stmt):
            if cue := lex.match_else(stmt.text):
                self._open_arm(frame, self._negative_label(), default=True)
                if cue.payload:
                    self._emit_statement(_replace_text(stmt, cue.payload))
                return index + 1
            if arm := self._as_case_label(stmt, inside_branch=True):
                label, payload = arm
                self._open_arm(frame, label)
                if payload:
                    self._emit_statement(_replace_text(stmt, payload))
                return index + 1

        if frame.kind == "branch" and frame.branch is not None and not frame.branch.arms:
            # Block form: "Если X:" with the body on the following lines.
            self._open_arm(frame, self._positive_label())

        if frame.kind == "parallel" and frame.parallel is not None:
            if frame.body_indent is None:
                frame.body_indent = stmt.indent
            if stmt.indent <= frame.body_indent:
                branch = IRSequence()
                frame.parallel.branches.append(branch)
                frame.sequence = branch

        return self._emit_statement(stmt, statements, index)

    def _unwind(self, stmt: _Statement) -> None:
        """Close every open block that the incoming statement leaves behind."""
        if self._is_arm_opener(stmt):
            for depth in range(len(self._stack) - 1, 0, -1):
                if self._accepts_arm(self._stack[depth], stmt):
                    del self._stack[depth + 1 :]
                    return
        while len(self._stack) > 1:
            frame = self._stack[-1]
            if stmt.indent > frame.open_indent:
                return
            self._stack.pop()

    def _accepts_arm(self, frame: _Frame, stmt: _Statement) -> bool:
        """Can ``frame`` take another decision arm opened by ``stmt``?

        An arm belongs to a decision when it sits between the decision header
        and the body of the previous arm — which covers both the inline style
        ("Иначе ..." at the same indent) and the block style ("Иначе:" outdented
        relative to the arm body it follows).
        """
        if frame.kind != "branch" or frame.branch is None:
            return False
        if stmt.indent < frame.open_indent:
            return False
        return frame.body_indent is None or stmt.indent <= frame.body_indent

    def _is_arm_opener(self, stmt: _Statement) -> bool:
        if lex.match_else(stmt.text):
            return True
        return self._as_case_label(stmt, inside_branch=True) is not None

    # -- statement handling --------------------------------------------------

    def _emit_statement(
        self,
        stmt: _Statement,
        statements: list[_Statement] | None = None,
        index: int = -1,
    ) -> int:
        """Translate one statement into IR; returns the next statement index."""
        next_index = index + 1 if index >= 0 else -1
        text = stmt.text.strip()
        if not text:
            return next_index
        self._current_indent = stmt.indent

        # 1. Explicit merge cue: close the enclosing blocks, keep the payload.
        if cue := lex.match_merge(text):
            self._close_blocks(stmt.indent)
            if cue.payload:
                self._emit_statement(_replace_text(stmt, cue.payload))
            return next_index

        # 2. Decisions come before everything else: a conditional sentence owns
        #    its whole text, and its branches are re-parsed as statements of
        #    their own.  Checking later would let a cue buried in the "иначе"
        #    part ("... и процесс завершается") swallow the decision.
        if cue := lex.match_condition(text):
            self._open_condition(cue.payload, stmt)
            return next_index
        if statements is not None and index >= 0 and self._is_branch_header(statements, index):
            self._open_question(text, stmt)
            return next_index

        # 3. Concurrency.
        if cue := lex.match_parallel(text):
            self._open_parallel(cue, text, stmt)
            return next_index

        # 4. Parenthetical asides are commentary, not steps.  Stripping them
        #    before the clause split keeps a conjunction *inside* the aside from
        #    tearing the sentence apart.
        body, asides = _strip_asides(text)
        if asides and body:
            self._emit_statement(_replace_text(stmt, body))
            for aside in asides:
                self._absorb_aside(aside, stmt)
            return next_index

        # 5. Coordinated clauses: "менеджер отклоняет заявку и процесс
        #    завершается" is a step followed by an end event, not one element.
        clauses = self._split_clauses(text)
        if len(clauses) > 1:
            for clause in clauses:
                self._emit_statement(_replace_text(stmt, clause))
            return next_index

        # 6. Process boundaries.
        if cue := lex.match_start(text):
            self._append(self._make_start_event(cue.payload or text, cue, stmt))
            return next_index
        if cue := lex.match_end(text):
            self._append(self._make_end_event(cue.payload, stmt))
            return next_index
        if self._ends_the_process(text):
            # "для студента этот экзамен заканчивается" - the subject is the
            # process this description is about, so the flow stops here.
            self._append(self._make_end_event("", stmt))
            return next_index

        # 7. Loops / jumps.
        if cue := lex.match_goto(text):
            self._append(
                IRGoto(
                    text=clean_label(text),
                    target=clean_label(cue.payload),
                    line=stmt.line,
                    source=text,
                )
            )
            return next_index

        # 8. Waiting and catching events.
        if cue := lex.match_wait(text):
            self._append(self._make_catch_event(cue.payload or text, stmt))
            return next_index
        if cue := lex.match_timer_prefix(text):
            self._append(self._make_timer_event(cue.keyword, stmt))
            if cue.payload:
                self._emit_statement(_replace_text(stmt, cue.payload))
            return next_index

        # 9. Plain steps.
        for element in self._make_activities(text, stmt):
            self._append(element)
        return next_index

    def _absorb_aside(self, aside: str, stmt: _Statement) -> None:
        """File a parenthetical remark where it belongs.

        An aside that says the process is over is a real end event; anything
        else documents the step it was attached to, so the wording survives in
        ``bpmn:documentation`` without cluttering the diagram.
        """
        if lex.match_end(aside) or self._ends_the_process(aside):
            self._append(self._make_end_event("", stmt))
            return
        items = self._stack[-1].sequence.items
        if not items:
            return
        element = items[-1]
        element.source = f"{element.source} [{aside}]" if element.source else aside

    def _ends_the_process(self, text: str) -> bool:
        """True when ``text`` says that *this* process is finished.

        Descriptions rarely repeat the words "процесс завершается"; they name
        the thing that ends ("этот экзамен заканчивается").  Matching the
        subject against the process name is what tells the two apart.
        """
        if not _COMPLETION_RE.search(text):
            return False
        name_stems = _stems(self._process.name)
        return bool(name_stems and name_stems & _stems(text))

    def _close_blocks(self, indent: int) -> None:
        while len(self._stack) > 1 and self._stack[-1].open_indent >= indent:
            self._stack.pop()

    def _append(self, element: IRActivity | IREvent | IRBranch | IRParallel | IRGoto) -> None:
        frame = self._stack[-1]
        if frame.kind == "branch" and frame.body_indent is None:
            frame.body_indent = self._current_indent
        frame.sequence.append(element)

    # -- decisions -----------------------------------------------------------

    def _open_condition(self, payload: str, stmt: _Statement) -> None:
        condition, positive, negative = self._split_condition(payload)

        # "Если X, то A. Если не X, то B." is one decision written as two
        # sentences - by far the most common way people describe a branch in
        # prose. Treating each sentence as its own gateway is the single
        # biggest source of wrong structure, so a condition that continues the
        # decision immediately before it extends that gateway instead.
        continued = self._decision_to_continue(condition)
        if continued is not None:
            frame = _Frame(
                sequence=IRSequence(),
                open_indent=stmt.indent,
                kind="branch",
                branch=continued,
                actor=self._current_actor(),
            )
            self._stack.append(frame)
            complementary = self._is_complement(continued, condition)
            self._open_arm(
                frame,
                self._arm_label_for(continued, condition),
                condition=condition,
                default=complementary,
            )
            if positive:
                self._emit_statement(_replace_text(stmt, positive))
            if negative:
                self._open_arm(frame, self._negative_label(), default=True)
                self._emit_statement(_replace_text(stmt, negative))
            return

        branch = IRBranch(
            text=self._as_question(condition),
            actor=self._current_actor(),
            branch_type=BranchType.EXCLUSIVE,
            line=stmt.line,
            source=stmt.text,
        )
        self._append(branch)
        frame = _Frame(
            sequence=IRSequence(),
            open_indent=stmt.indent,
            kind="branch",
            branch=branch,
            actor=self._last_actor,
        )
        self._stack.append(frame)

        if positive:
            self._open_arm(frame, self._positive_label(), condition=condition)
            self._emit_statement(_replace_text(stmt, positive))
        if negative:
            if not branch.arms:
                self._open_arm(frame, self._positive_label(), condition=condition)
            self._open_arm(frame, self._negative_label(), default=True)
            self._emit_statement(_replace_text(stmt, negative))

    def _decision_to_continue(self, condition: str) -> IRBranch | None:
        """The gateway this condition belongs to, if it continues one.

        Only the immediately preceding sibling qualifies: once another step has
        intervened, a new "Если" starts a new decision.
        """
        items = self._stack[-1].sequence.items
        previous = items[-1] if items else None
        if not isinstance(previous, IRBranch):
            return None
        if previous.branch_type is not BranchType.EXCLUSIVE:
            return None
        if not previous.arms or len(previous.arms) > 3:
            return None
        if any(arm.is_default for arm in previous.arms):
            return None
        first = _first_condition(previous)
        if not first or not condition:
            return None

        negated_before = _is_negated(first)
        negated_now = _is_negated(condition)
        context = " ".join(
            [first, *(element.text for arm in previous.arms for element in arm.body)]
        )
        if negated_before != negated_now:
            # One says X, the other not-X: complementary as long as they are
            # about the same thing at all.
            return previous if _shares_topic(condition, context) else None
        # Both stated positively ("согласен" / "хочет апеллировать"): only when
        # they describe alternatives for the same subject.
        return previous if _same_subject(condition, first) else None

    def _is_complement(self, branch: IRBranch, condition: str) -> bool:
        """Does this condition answer the gateway's question the other way?

        Only a decision that still has a single arm can be completed this way:
        once two outcomes are on the gateway, a further condition is a third
        alternative, not the missing half of a yes/no pair.
        """
        if len(branch.arms) != 1:
            return False
        return _is_negated(condition) != _is_negated(_first_condition(branch))

    def _arm_label_for(self, branch: IRBranch, condition: str) -> str:
        """Label for an arm added to an existing decision."""
        if self._is_complement(branch, condition):
            # The arm already on the gateway answers "yes" - whichever of the
            # two sentences carried the negation - so this one answers "no".
            return self._negative_label()
        # A parallel alternative ("согласен" / "хочет апеллировать") is not a
        # yes/no answer; naming it after its own condition also keeps two arms
        # of one gateway from reading identically.
        return capitalize_first(clean_label(condition))[:40]

    def _open_question(self, text: str, stmt: _Statement) -> None:
        """Open a decision declared by a header line or an explicit question.

        A header that *performs* an action ("Оператор определяет категорию
        обращения:") describes two BPMN elements, not one: the activity that
        produces the answer, and the gateway that routes on it.  Splitting them
        is what a modeller would do by hand, so the parser does it too.
        """
        actor, remainder = self._extract_actor(clean_label(text))
        if actor:
            self._last_actor = actor
        effective_actor = actor or self._current_actor()

        words = remainder.split()
        question = remainder
        if len(words) > 1 and looks_like_verb(words[0]):
            self._append(
                IRActivity(
                    text=capitalize_first(_to_infinitive(remainder)),
                    actor=effective_actor,
                    activity_type=lex.classify_activity(remainder, effective_actor),
                    line=stmt.line,
                    source=stmt.text,
                )
            )
            question = to_nominative_object(" ".join(words[1:]))

        branch = IRBranch(
            text=self._as_question(question or remainder),
            actor=effective_actor,
            branch_type=BranchType.EXCLUSIVE,
            line=stmt.line,
            source=stmt.text,
        )
        self._append(branch)
        self._stack.append(
            _Frame(
                sequence=IRSequence(),
                open_indent=stmt.indent,
                kind="branch",
                branch=branch,
                actor=effective_actor,
            )
        )

    def _open_arm(
        self,
        frame: _Frame,
        label: str,
        *,
        condition: str = "",
        default: bool = False,
    ) -> IRArm:
        assert frame.branch is not None
        is_default = default and not any(arm.is_default for arm in frame.branch.arms)
        arm = IRArm(
            label=label,
            body=IRSequence(),
            condition="" if is_default else condition,
            is_default=is_default,
        )
        frame.branch.add_arm(arm)
        frame.sequence = arm.body
        self._last_actor = frame.actor
        return arm

    def _split_condition(self, payload: str) -> tuple[str, str, str]:
        """Split "X, то Y, иначе Z" into its three parts."""
        head, negative = _split_once(_ELSE_SPLIT_RE, payload)
        condition, positive = _split_once(_THEN_SPLIT_RE, head)
        if not positive and "," in head:
            condition, _, positive = head.partition(",")
        return clean_label(condition), positive.strip(), negative.strip()

    def _is_branch_header(self, statements: list[_Statement], index: int) -> bool:
        """A question, or a "header:" whose following lines enumerate outcomes."""
        stmt = statements[index]
        if lex.QUESTION_MARK_RE.search(stmt.text):
            return True
        if not stmt.text.rstrip().endswith(":"):
            return False
        labelled = 0
        for follower in statements[index + 1 :]:
            if follower.indent <= stmt.indent:
                break
            if self._as_case_label(follower, inside_branch=True):
                labelled += 1
            else:
                break
        return labelled >= 2

    def _as_case_label(self, stmt: _Statement, *, inside_branch: bool) -> tuple[str, str] | None:
        """Recognise "Да — выставить счёт" style decision arms."""
        cue = lex.match_case_label(stmt.text)
        if cue is None:
            return None
        match = lex.CASE_LABEL_RE.match(stmt.text)
        assert match is not None
        label = clean_label(match.group("label"))
        payload = match.group("payload").strip()
        if not label or not payload:
            return None
        words = label.split()
        if len(words) > 3:
            return None
        if any(looks_like_verb(word) for word in words):
            return None
        if lex.arm_polarity(label) is None:
            # Outside an obvious yes/no context only short, listed labels qualify,
            # otherwise "Менеджер: проверяет заявку" would masquerade as an arm.
            if lex.is_role_word(words[0]):
                return None
            if not (inside_branch and (stmt.listed or len(words) <= 2)):
                return None
        return capitalize_first(label), payload

    # -- concurrency ---------------------------------------------------------

    def _open_parallel(self, cue: lex.Cue, text: str, stmt: _Statement) -> None:
        parallel = IRParallel(text=clean_label(text), line=stmt.line, source=stmt.text)
        payload = cue.payload
        if not payload:
            # "A и B выполняются одновременно" - the enumeration precedes the cue.
            payload = text[: cue.span[0]].strip()
        branches = self._split_enumeration(payload)
        if len(branches) >= 2:
            self._append(parallel)
            for fragment in branches:
                sequence = IRSequence()
                parallel.branches.append(sequence)
                self._stack.append(
                    _Frame(sequence=sequence, open_indent=stmt.indent, kind="inline-parallel")
                )
                self._emit_statement(_replace_text(stmt, fragment))
                self._stack.pop()
            return
        # Block form: the branches follow on the next (indented) lines.
        self._append(parallel)
        self._stack.append(
            _Frame(
                sequence=IRSequence(),
                open_indent=stmt.indent,
                kind="parallel",
                parallel=parallel,
                actor=self._last_actor,
            )
        )

    def _split_enumeration(self, payload: str) -> list[str]:
        if not payload:
            return []
        fragments = [clean_label(part) for part in lex.LIST_SPLIT_RE.split(payload)]
        return [fragment for fragment in fragments if len(fragment) > 2]

    # -- leaf elements -------------------------------------------------------

    def _make_start_event(self, payload: str, cue: lex.Cue, stmt: _Statement) -> IREvent:
        self._adopt_process_name(stmt.text[: cue.span[0]])
        # "начинается с заявки" puts the trigger in the genitive; the cue tells
        # us so, and only then is the conversion unambiguous.
        text = _MOMENT_LEAD_RE.sub("", clean_label(payload))
        label = (
            from_genitive(text) if _GENITIVE_CUE_RE.search(cue.prefix) else nominalize(text)
        ) or _DEFAULT_NAMES[self._language]["start"]
        actor, remainder = self._extract_actor(label)
        # "Клиент звонит" must not become an event called "Звонит": once the
        # actor is removed, a single leftover word is not a usable event name.
        if actor and len(remainder.split()) > 1:
            label = remainder
        trigger, timer = lex.classify_event_trigger(label)
        return IREvent(
            text=capitalize_first(label) or _DEFAULT_NAMES[self._language]["start"],
            actor=actor,
            position=EventPosition.START,
            trigger=trigger,
            timer=timer,
            line=stmt.line,
            source=stmt.text,
        )

    def _adopt_process_name(self, prefix: str) -> None:
        """Take the process name from the sentence that opens the description.

        "Бизнес-процесс «Сдача экзамена» начинается с ..." names the process in
        passing; a heading is not the only place a description states it.
        """
        if self._process.name:
            return
        if match := _QUOTED_PROCESS_RE.search(prefix):
            self._process.name = capitalize_first(clean_label(match.group("name")))

    def _make_end_event(self, payload: str, stmt: _Statement) -> IREvent:
        label = clean_label(payload)
        documentation = ""
        if label and _is_instrumental(label.split()[0]):
            # "Процесс завершается подписанием" - the payload describes *how* the
            # process ends, which is documentation, not a label.
            documentation, label = label, ""
        label = label or _DEFAULT_NAMES[self._language]["end"]
        trigger, _ = lex.classify_event_trigger(label)
        if trigger not in {EventTrigger.TERMINATE, EventTrigger.ERROR, EventTrigger.ESCALATION}:
            trigger = EventTrigger.NONE
        event = IREvent(
            text=capitalize_first(label),
            actor=self._last_actor,
            position=EventPosition.END,
            trigger=trigger,
            line=stmt.line,
            source=stmt.text,
        )
        if documentation:
            event.source = f"{stmt.text} [{documentation}]"
        return event

    def _make_catch_event(self, payload: str, stmt: _Statement) -> IREvent:
        actor, label = self._extract_actor(nominalize(clean_label(payload)))
        trigger, timer = lex.classify_event_trigger(stmt.text)
        if trigger is EventTrigger.NONE:
            trigger = EventTrigger.MESSAGE
        name = capitalize_first(label) or clean_label(stmt.text)
        return IREvent(
            text=name,
            actor=actor or self._current_actor(),
            position=EventPosition.INTERMEDIATE_CATCH,
            trigger=trigger,
            timer=timer,
            line=stmt.line,
            source=stmt.text,
        )

    def _make_timer_event(self, phrase: str, stmt: _Statement) -> IREvent:
        _, timer = lex.classify_event_trigger(phrase)
        return IREvent(
            text=capitalize_first(clean_label(phrase)),
            actor=self._current_actor(),
            position=EventPosition.INTERMEDIATE_CATCH,
            trigger=EventTrigger.TIMER,
            timer=timer or clean_label(phrase),
            line=stmt.line,
            source=stmt.text,
        )

    def _make_activities(self, text: str, stmt: _Statement) -> list[IRActivity]:
        body = lex.strip_leading_connective(text)
        body, pronoun_subject = _resolve_impersonal(body)
        actor, remainder = self._extract_actor(body)
        if actor is None and pronoun_subject:
            # "он тянет билет" points back at whoever the decision is about.
            actor = self._condition_actor()
        if actor:
            self._last_actor = actor
        effective_actor = actor or self._current_actor()

        activities: list[IRActivity] = []
        for fragment in [remainder]:
            label = clean_label(fragment)
            if not label:
                continue
            activity_type = lex.classify_activity(f"{effective_actor or ''} {label}", effective_actor)
            name = _to_infinitive(label) if self.options.infinitive_names else label
            activities.append(
                IRActivity(
                    text=capitalize_first(name),
                    actor=effective_actor,
                    activity_type=activity_type,
                    line=stmt.line,
                    source=stmt.text,
                )
            )
        return activities

    def _split_clauses(self, text: str) -> list[str]:
        """Split a sentence into independently modelled clauses.

        A split only happens when *every* fragment can stand on its own as a
        step — it starts with a verb or carries a structural cue.  Otherwise
        the conjunction joins objects ("счёт и акт"), not actions, and the
        sentence stays whole.
        """
        if not self.options.split_conjoined_actions:
            return [text]
        parts = [part.strip() for part in _CONJUNCTION_SPLIT_RE.split(text) if part.strip()]
        parts = [fragment for part in parts for fragment in self._split_on_commas(part)]
        if len(parts) < 2:
            return [text]
        if all(self._is_actionable(part) for part in parts):
            return parts
        return [text]

    def _split_on_commas(self, text: str) -> list[str]:
        """Split "тянет билет, называет номер" into two steps.

        Only a comma followed by a finite verb separates clauses; the far more
        common "сообщает, что ..." and "спрашивает, необходимо ли ..." keep
        their subordinate clause, which is part of the step, not another one.
        """
        parts = [part.strip() for part in _COMMA_SPLIT_RE.split(text) if part.strip()]
        if len(parts) < 2:
            return [text]
        merged = [parts[0]]
        for part in parts[1:]:
            words = part.split()
            starts_a_clause = (
                len(words) > 1
                and looks_like_verb(_bare(words[0]))
                and not looks_like_verb(_bare(merged[-1].split()[-1]))
            )
            if starts_a_clause:
                merged.append(part)
            else:
                merged[-1] = f"{merged[-1]}, {part}"
        return merged

    def _is_actionable(self, fragment: str) -> bool:
        if any(
            matcher(fragment)
            for matcher in (lex.match_goto, lex.match_wait, lex.match_end, lex.match_start)
        ):
            return True
        if self._ends_the_process(fragment):
            return True
        words = fragment.split()
        return any(looks_like_verb(_bare(word)) for word in words[:2])

    # -- actors --------------------------------------------------------------

    def _current_actor(self) -> str | None:
        return self._last_actor if self.options.inherit_actor else None

    def _condition_actor(self) -> str | None:
        """The role the enclosing decision is about.

        "Если студент не готов, он отвечает" - the pronoun refers to the
        condition's subject, which is not necessarily whoever acted last.
        """
        if not self.options.inherit_actor:
            return None
        for frame in reversed(self._stack):
            if frame.kind != "branch" or frame.branch is None:
                continue
            for word in _first_condition(frame.branch).split():
                bare = _bare(word)
                if lex.is_role_word(bare):
                    return normalize_actor(bare)
        return None

    def _extract_actor(self, text: str) -> tuple[str | None, str]:
        """Split a step into (actor, action).

        Four surface forms are recognised, in decreasing order of explicitness:
        ``[Роль] действие``, ``Роль: действие``, ``Роль делает X`` and the
        passive ``X выполняется ролью`` / ``X is done by the role``.
        """
        stripped = text.strip()
        if match := _BRACKET_ACTOR_RE.match(stripped):
            return normalize_actor(match.group("actor")), match.group("rest").strip()

        if match := _COLON_ACTOR_RE.match(stripped):
            candidate = match.group("actor").strip()
            words = candidate.split()
            names_a_role = lex.is_role_word(words[0]) or all(
                word[:1].isupper() for word in words
            )
            if len(words) <= 3 and names_a_role and not any(
                looks_like_verb(word) for word in words
            ):
                return normalize_actor(candidate), match.group("rest").strip()

        words = stripped.split()
        # Shortest actor first: "бухгалтер выставляет счёт" must yield the role
        # "бухгалтер", never the two-word prefix "бухгалтер выставляет".
        for size in (1, 2, 3):
            if len(words) <= size:
                continue
            head, tail = words[:size], words[size:]
            # "преподаватель спрашивает, ..." - the comma is glued to the verb
            # and would otherwise hide it.
            if not looks_like_verb(_bare(tail[0])):
                continue
            # A role name never contains a preposition: "студент от
            # преподавателя получает" names the student, not a three-word role.
            for index, word in enumerate(head):
                if word.casefold() in _PREPOSITIONS:
                    head = head[:index]
                    break
            while head and head[-1].casefold() in _ADVERBS:
                head, tail = head[:-1], [*head[-1:], *tail]
            if head and any(lex.is_role_word(word) for word in head):
                return normalize_actor(" ".join(head)), " ".join(tail)

        # "Исходя из ответа преподаватель называет оценку": an adverbial preface
        # may stand in front of the role.  What precedes the role describes the
        # circumstances, not the action, so only the verb phrase is the label.
        for position in range(1, min(len(words) - 1, 8)):
            previous = words[position - 1].casefold()
            word = _bare(words[position])
            if previous in _PREPOSITIONS or _is_instrumental(word):
                continue
            if lex.is_role_word(word) and looks_like_verb(_bare(words[position + 1])):
                return normalize_actor(word), " ".join(words[position + 1 :])

        if match := _BY_ACTOR_RE.search(stripped):
            actor = match.group("actor")
            if lex.is_role_word(actor.split()[-1]):
                return normalize_actor(actor), stripped[: match.start()].strip()

        for position, word in enumerate(words):
            if position == 0 or words[position - 1].casefold() in _PREPOSITIONS:
                continue  # "связывается с клиентом" names an object, not the actor
            nominative = _to_nominative(word)
            if nominative:
                remainder = " ".join(words[:position] + words[position + 1 :])
                return normalize_actor(nominative), _strip_dangling_preposition(remainder)
        return None, stripped

    # -- labels --------------------------------------------------------------

    def _positive_label(self) -> str:
        return _ARM_LABELS[self._language][0]

    def _negative_label(self) -> str:
        return _ARM_LABELS[self._language][1]

    def _as_question(self, condition: str) -> str:
        label = capitalize_first(clean_label(condition))
        if not label:
            return "?"
        return label if label.endswith("?") else f"{label}?"

    # -- finalisation --------------------------------------------------------

    def _post_process(self, process: IRProcess) -> None:
        if not self.options.detect_lanes:
            for element in _iter_elements(process.root):
                element.actor = None
            return
        for element in _iter_elements(process.root):
            if element.actor:
                process.ensure_lane(element.actor)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _replace_text(stmt: _Statement, text: str) -> _Statement:
    return _Statement(text=text.strip(), indent=stmt.indent, line=stmt.line, listed=stmt.listed)


def _split_once(pattern: re.Pattern[str], text: str) -> tuple[str, str]:
    match = pattern.search(text)
    if match is None:
        return text, ""
    return text[: match.start()], text[match.end() :]


def _is_instrumental(word: str) -> bool:
    lowered = word.casefold()
    return len(lowered) > 5 and lowered.endswith(_INSTRUMENTAL_ENDINGS)


_NEGATION_RE = re.compile(r"(?:^|\s)(?:не|нет|без)\b|\bnot\b|\bno\b", re.IGNORECASE)
_SUBJECT_STOP = frozenset(
    {"если", "когда", "при", "в", "во", "на", "то", "тогда", "это", "такая", "такой", "if", "when"}
)


def _is_negated(condition: str) -> bool:
    return bool(_NEGATION_RE.search(condition))


def _first_condition(branch: IRBranch) -> str:
    """The condition the decision was originally opened with."""
    if branch.arms and branch.arms[0].condition:
        return branch.arms[0].condition
    return branch.text.rstrip("?")


def _stems(text: str) -> set[str]:
    words = re.findall(r"\w+", text.casefold())
    return {
        word[:4]
        for word in words
        if len(word) > 3 and word not in _SUBJECT_STOP and word not in _PREPOSITIONS
    }


def _shares_topic(condition: str, context: str) -> bool:
    """Do the condition and the decision's context talk about the same thing?"""
    left, right = _stems(condition), _stems(context)
    return bool(left & right)


def _same_subject(left: str, right: str) -> bool:
    """Both conditions open with the same significant word."""
    first_left = next(iter(_significant_words(left)), "")
    first_right = next(iter(_significant_words(right)), "")
    return bool(first_left) and first_left[:4] == first_right[:4]


def _significant_words(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\w+", text.casefold())
        if len(word) > 3 and word not in _SUBJECT_STOP and word not in _PREPOSITIONS
    ]


def _bare(word: str) -> str:
    """A token without the punctuation that clings to it."""
    return word.strip(".,;:!?()«»\"'")


def _strip_asides(text: str) -> tuple[str, list[str]]:
    """Separate a sentence from the remarks its author put in brackets."""
    asides = [match.group(1).strip() for match in _ASIDE_RE.finditer(text)]
    body = _ASIDE_RE.sub("", text).strip()
    if "(" in body:
        # An unclosed bracket - frequent in hand-written descriptions - opens a
        # remark that simply runs to the end of the sentence.
        head, _, tail = body.partition("(")
        body, trailing = head.strip(), tail.strip()
        if trailing:
            asides.append(trailing)
    return clean_label(body), [aside for aside in asides if aside]


def _resolve_impersonal(text: str) -> tuple[str, bool]:
    """Rewrite subject-less prose as an action; report a dropped pronoun.

    Three surface forms hide the step behind scaffolding: a pronoun standing in
    for the actor ("он тянет билет"), an impersonal announcement ("происходит
    проверка") and a verb-initial passive ("дается доп. время").
    """
    words = text.split()
    if not words:
        return text, False
    pronoun = False
    head = _bare(words[0]).casefold()
    if len(words) > 1 and looks_like_verb(_bare(words[1])):
        if head in _PRONOUN_SUBJECTS:
            pronoun = True
            words = words[1:]
        elif head in _PRONOUN_OBJECTS:
            words = words[1:]
        head = _bare(words[0]).casefold()
    if len(words) > 1 and head in _IMPERSONAL_VERBS:
        # The noun phrase after the verb *is* the step.
        return " ".join(words[1:]), pronoun
    if head in _PASSIVE_ACTIONS:
        return " ".join([_PASSIVE_ACTIONS[head], *words[1:]]), pronoun
    return " ".join(words), pronoun


def _strip_dangling_preposition(text: str) -> str:
    words = text.split()
    while words and words[-1].casefold() in _PREPOSITIONS:
        words.pop()
    return " ".join(words)


def _to_nominative(word: str) -> str | None:
    """Recover a nominative role from an instrumental form ("менеджером")."""
    lowered = word.casefold().strip(" .,:;")
    for ending in _INSTRUMENTAL_ENDINGS:
        if lowered.endswith(ending) and len(lowered) > len(ending) + 3:
            candidate = lowered[: -len(ending)]
            if lex.is_role_word(candidate):
                return candidate
            if lex.is_role_word(candidate + "а"):
                return candidate + "а"
            if lex.is_role_word(candidate + "ия"):
                return candidate + "ия"
    return None


def _iter_elements(sequence: IRSequence) -> Iterator[IRElement]:
    return walk(sequence)


def parse_text(raw_text: str, options: ParserOptions | None = None) -> IRProcess:
    """Convenience wrapper around :class:`NaturalLanguageParser`."""
    return NaturalLanguageParser(options).parse(raw_text)
