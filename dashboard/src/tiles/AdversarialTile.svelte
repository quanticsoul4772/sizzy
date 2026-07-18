<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B3.8: adversarial self-tester — runs grouped by outcome; regressions surfaced prominently.
  // rev 0.3.88 (feature B): also carries loop fault-injection — probes that inject a real failure
  // class into a hermetic build; a fault-handling regression (a silent orphan) is surfaced like a
  // gate regression.
  let runs = $state([]); // {probe_name, target_gate, outcome}
  let regressions = $state([]); // {probe_name, gate_name, unexpected_allow_reason}
  let faultRuns = $state([]); // {probe_name, fault_class, outcome}
  let faultRegressions = $state([]); // {probe_name, fault_class, invariant_numbers, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (msg.event_type === 'adversarial_test_run') {
      runs = [...runs, { probe_name: p.probe_name, target_gate: p.target_gate, outcome: p.outcome }].slice(-50);
    } else if (msg.event_type === 'gate_regression_detected') {
      regressions = [...regressions, { probe_name: p.probe_name, gate_name: p.gate_name, reason: p.unexpected_allow_reason }].slice(-50);
    } else if (msg.event_type === 'loop_fault_run') {
      faultRuns = [...faultRuns, { probe_name: p.probe_name, fault_class: p.fault_class, outcome: p.outcome }].slice(-50);
    } else if (msg.event_type === 'fault_handling_regression') {
      faultRegressions = [...faultRegressions, { probe_name: p.probe_name, fault_class: p.fault_class, invariant_numbers: p.invariant_numbers, detail: p.detail }].slice(-50);
    }
  }

  onMount(() => {
    unsubscribe = subscribe(
      ['adversarial_test_run', 'gate_regression_detected', 'loop_fault_run', 'fault_handling_regression'],
      apply,
      () => (connected = true),
    );
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Adversarial self-tester</h2>
  <small>proj_adversarial</small>
  {#if regressions.length > 0}
    <ul>
      {#each regressions as r, i (i)}
        <li><strong>REGRESSION</strong> {r.gate_name} ({r.probe_name}): {r.reason}</li>
      {/each}
    </ul>
  {/if}
  {#if faultRegressions.length > 0}
    <ul>
      {#each faultRegressions as r, i (i)}
        <li><strong>LOOP-FAULT REGRESSION</strong> {r.fault_class} ({r.probe_name}): Inv {r.invariant_numbers?.join(', ')} — {r.detail}</li>
      {/each}
    </ul>
  {/if}
  {#if runs.length === 0}
    <p>no adversarial self-tester yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each runs as r, i (i)}
        <li><span>[{r.outcome}]</span> {r.target_gate} ({r.probe_name})</li>
      {/each}
    </ul>
  {/if}
  {#if faultRuns.length > 0}
    <small>loop faults</small>
    <ul>
      {#each faultRuns as r, i (i)}
        <li><span>[{r.outcome}]</span> {r.fault_class} ({r.probe_name})</li>
      {/each}
    </ul>
  {/if}
</section>
