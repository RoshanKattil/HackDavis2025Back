import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { ChainCustody } from "../target/types/chain_custody";
import { Keypair, SystemProgram, PublicKey } from "@solana/web3.js";
import { assert } from "chai";

describe("chain-custody", () => {
  // Configure the client to use the local cluster.
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.ChainCustody as Program<ChainCustody>;

  it("Is initialized!", async () => {
    // 1) Generate a new Keypair for the Material account
    const materialKeypair = Keypair.generate();

    // 2) Call initializeMaterial with that account
    const materialId = "MatA123";
    await program.methods
      .initializeMaterial(materialId)
      .accounts({
        materialAccount: materialKeypair.publicKey,           // <— provide it here
        initializer:        provider.wallet.publicKey,
        systemProgram:      SystemProgram.programId,
      })
      .signers([materialKeypair])                             // <— and sign for it
      .rpc();

  it("Transfers custody", async () => {
    const materialKeypair = Keypair.generate();

    // 1) initialize
    await program.methods
      .initializeMaterial("MatB456")
      .accounts({
        materialAccount: materialKeypair.publicKey,
        initializer:      provider.wallet.publicKey,
        systemProgram:    SystemProgram.programId,
      })
      .signers([materialKeypair])
      .rpc();

    // 2) transfer
    const newHolder = Keypair.generate();
    await program.methods
      .transferMaterial(newHolder.publicKey)
      .accounts({
        materialAccount: materialKeypair.publicKey,
        currentHolder:   provider.wallet.publicKey,
      })
      .rpc();

    // 3) Fetch the on‑chain account and assert its state
    const account = await program.account.material.fetch(materialKeypair.publicKey);
    assert.ok(account.currentHolder.equals(provider.wallet.publicKey));
    assert.equal(account.lastSequence.toNumber(), 0);
  });
});
