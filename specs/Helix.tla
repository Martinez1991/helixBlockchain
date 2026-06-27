-------------------------------- MODULE Helix --------------------------------
(***************************************************************************)
(* A TLA+ model of the safety core of Helix's IBFT-style consensus for a   *)
(* single block height. It abstracts cryptography (signatures are modelled  *)
(* by honest senders) and focuses on the agreement property that matters:   *)
(*                                                                          *)
(*   Agreement: no two correct validators commit different blocks.          *)
(*                                                                          *)
(* The proof obligation reduces to quorum intersection: with N validators,  *)
(* f = (N-1) \div 3 Byzantine, quorum Q = N - f, any two quorums intersect   *)
(* in at least f+1 validators, hence at least one correct validator — so two *)
(* different blocks cannot both gather a commit-quorum.                      *)
(*                                                                          *)
(* Check with TLC using Helix.cfg (e.g. N=4). See specs/README.md.          *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Validators,   \* set of validator ids
          Byz,          \* subset of Validators that are Byzantine
          Blocks        \* set of candidate block values (>= 2 to be interesting)

ASSUME ByzAssume == Byz \subseteq Validators
ASSUME BlocksAssume == Cardinality(Blocks) >= 1

N == Cardinality(Validators)
F == (N - 1) \div 3
Quorum == N - F
Correct == Validators \ Byz

VARIABLES
    prepares,  \* prepares[b]  = set of validators that have PREPAREd block b
    commits,   \* commits[b]   = set of validators that have COMMITted block b
    committed  \* committed[v] = the block v locked in, or "none"

vars == <<prepares, commits, committed>>

NoBlock == CHOOSE x : x \notin Blocks

Init ==
    /\ prepares  = [b \in Blocks |-> {}]
    /\ commits   = [b \in Blocks |-> {}]
    /\ committed = [v \in Validators |-> NoBlock]

\* A correct validator PREPAREs a block only if it has not PREPAREd a different
\* one (no equivocation — this is what the vote journal enforces in code).
Prepare(v, b) ==
    /\ v \in Correct
    /\ \A c \in Blocks : v \in prepares[c] => c = b
    /\ prepares' = [prepares EXCEPT ![b] = @ \cup {v}]
    /\ UNCHANGED <<commits, committed>>

\* A correct validator COMMITs b only after seeing a quorum of PREPAREs for b
\* and not having committed a different block.
Commit(v, b) ==
    /\ v \in Correct
    /\ Cardinality(prepares[b]) >= Quorum
    /\ committed[v] \in {NoBlock, b}
    /\ commits' = [commits EXCEPT ![b] = @ \cup {v}]
    /\ committed' = [committed EXCEPT ![v] = b]
    /\ UNCHANGED prepares

\* Byzantine validators may PREPARE/COMMIT anything (modelled as free moves),
\* but cannot forge a correct validator's vote.
ByzMove(v, b) ==
    /\ v \in Byz
    /\ \/ prepares' = [prepares EXCEPT ![b] = @ \cup {v}] /\ UNCHANGED <<commits, committed>>
       \/ commits'  = [commits  EXCEPT ![b] = @ \cup {v}] /\ UNCHANGED <<prepares, committed>>

Next ==
    \E v \in Validators, b \in Blocks :
        \/ Prepare(v, b)
        \/ Commit(v, b)
        \/ ByzMove(v, b)

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* A block is "decided" when a quorum of validators committed it.          *)
(***************************************************************************)
Decided(b) == Cardinality(commits[b]) >= Quorum

\* Safety: at most one block can be decided. Two quorums of size N-F always
\* intersect in a correct validator (since 2(N-F) - N = N - 2F >= F+1 > F),
\* and a correct validator never commits two different blocks.
Agreement == \A b1, b2 \in Blocks : (Decided(b1) /\ Decided(b2)) => (b1 = b2)

\* A correct validator never holds two different committed values.
NoCorrectEquivocation ==
    \A v \in Correct, b1, b2 \in Blocks :
        (v \in commits[b1] /\ v \in commits[b2]) => (b1 = b2)

THEOREM Spec => []Agreement
=============================================================================
