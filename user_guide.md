# Dipesh Medical Hall: User Guide

## Start the application

1. Install Python 3.11 or newer and the packages listed in `requirements.txt`.
2. Run `python main.py` from the project folder.
3. The local database is created automatically on the first run.
4. Use **Language / भाषा** in the left sidebar and choose **नेपाली** to switch the active screens and messages to Nepali. Your choice is remembered next time.

## Medicines and stock (औषधि तथा स्टक)

1. Choose **Medicines & Stock** from the left menu.
2. Select **+ Medicine** and enter the name, optional generic name, category, barcode, rates, reorder level, and shelf location.
3. Select the saved medicine, then choose **+ Batch**. Enter its batch number, dates, quantity, and purchase/selling rates.
4. Search by medicine name, generic/salt name, barcode, or batch number. Use the filter to review expired, expiring, low, or out-of-stock items.
5. Select a batch and choose **Adjust stock** to record damage, loss, or a correction. Enter a signed quantity and a reason.
6. Use **Write off expired** to set expired batch quantities to zero. Confirm the action; the adjustment is recorded in the database.
7. Medicine deletion asks for confirmation. Medicines with batch history cannot be deleted, preserving the stock record.

The stock service allocates sales quantities FEFO (first expiry, first out) and rejects expired batches and insufficient stock. Billing is not enabled in this checkpoint, so FEFO is currently verified by tests and ready for the sales phase.

## Purchases (खरिद)

1. Choose **Purchases** from the left menu and select a dealer. Add the invoice number, invoice and due dates, payment type, and remark.
2. Select **+ Add item**. Choose the medicine and enter its batch, dates, billed quantity, optional free quantity, purchase/selling rates, discount, and tax.
3. Review the item list and bill total, then choose **Save purchase and update stock**. The purchase, batch stock, and dealer-ledger entry save together. Cash purchases are marked paid on the invoice date; credit purchases remain payable.
4. Search purchase history by invoice number or dealer.

## Dealer Ledger (डिलर खाता)

1. Choose **Dealer Ledger**, then **+ Dealer** to enter dealer contact and credit-term details.
2. Select the dealer and date range. **+ Invoice debit** records an invoice amount owed; **+ Payment credit** records a payment and its method. Add remarks such as a cheque number or part-payment note.
3. The table follows the paper book: **Date | Invoice No. | Debit | Date | Credit | Remarks | Balance**. The summary includes opening balance, date-range debit/credit totals, and closing balance.
4. Choose **Export Excel** or **Export PDF** and select the destination file.

## Billing (बिक्री बिल)

1. Choose **Billing (Sales)**. Search or scan the medicine barcode, select a medicine, set quantity and any line discount, then choose **Add to bill**.
2. Review the bill, optionally apply a whole-bill discount, and select Cash, Online / QR, or Credit. A customer is required for credit sales; the app warns if the credit limit will be exceeded.
3. Choose **Save bill** or press F2. Stock is deducted from the earliest-expiry unexpired batches; insufficient stock blocks the sale.
4. Use **Hold bill** and **Resume held bill** to pause and continue an unsaved bill. Select a saved bill in Sales history and choose **Return remaining items** to restock its original batches and adjust customer credit.
5. Select a bill and choose **Print selected** or press F5 to open the system print preview.

## Customer Credit (ग्राहक उधार)

1. Choose **Customer Credit**, then **+ Customer** to save a name, phone, address, and credit limit.
2. Select a customer to see the paper-style ledger, opening/closing balances, and date-range totals.
3. Choose **Receive payment** to enter a payment; optionally link it to a credit bill. Payments cannot exceed that bill's remaining amount.
4. Choose an ageing bucket to review outstanding credit. **Send reminder** opens the computer's default SMS handler with a prefilled balance message.

Expenses, Reports, and Settings are still planned for later phases. Choose **Language / भाषा** in the sidebar to switch the active application screens and messages between English and Nepali; the choice is saved locally.

Dashboard and stock alert figures currently cover medicine and expiry data only. Nepali menu labels and active-page prompts are available through the sidebar language selector.

**Testing note:** `python seed.py` adds disposable sample medicines to the local database. Do not run it against a live production database.
