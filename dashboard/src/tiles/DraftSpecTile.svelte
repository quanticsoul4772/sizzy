<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: spec_drafted / spec_signed — "ready to sign" for unsigned drafts (B1.3).
  let specs = $state([]); // {spec_id, title, signed}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (msg.event_type === 'spec_drafted') {
      specs = [...specs.filter((s) => s.spec_id !== p.spec_id), { spec_id: p.spec_id, title: p.title, signed: false }];
    } else if (msg.event_type === 'spec_signed') {
      specs = specs.map((s) => (s.spec_id === p.spec_id ? { ...s, signed: true } : s));
    }
  }

  onMount(() => {
    unsubscribe = subscribe(['spec_drafted', 'spec_signed'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Drafted specs</h2>
  <small>proj_draft_spec</small>
  {#if specs.length === 0}
    <p>no drafted specs yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each specs as s (s.spec_id)}
        <li>
          {s.title} <small>({s.spec_id})</small>
          {#if s.signed}
            <span> — signed</span>
          {:else}
            <span class="ready-to-sign"> — ready to sign: <code>devharness sign {s.spec_id}</code></span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
