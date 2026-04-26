-- 校园二手交易平台 — 建表、约束、视图、种子数据（PostgreSQL）
--
-- 循证来源：
--   1) 作业 PDF 文字要求：status 0/1、orders.item_id 唯一、外键关系、两类视图、购买事务等。
--   2) 实现计划（附件）：User 四行 u001–u004；Item 五行，其中 i002/i004 已售；Orders 两行 o001/o002。
--   3) 作业 PDF 内初始数据表为图片，本仓库无法 OCR 出每个单元格；下列 user_name/phone/品名/价格/日期
--      为与上述 ID、status、订单引用关系自洽的示例数据。若与课堂截图字面不一致，请只改 INSERT 值，
--      勿改表结构与主外键。
--   4) 「生活用品」在作业文字与常见课件中对应英文类别名 DailyGoods；查询可用 category = 'DailyGoods'，
--      并在说明文档中写明对应关系（计划默认方案 A）。

BEGIN;

DROP VIEW IF EXISTS sold_items_view CASCADE;
DROP VIEW IF EXISTS unsold_items_view CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS item CASCADE;
DROP TABLE IF EXISTS "User" CASCADE;

-- 「User」为作业表名；PostgreSQL 中 user 为保留关键字，故对表名使用双引号。
CREATE TABLE "User" (
    user_id   VARCHAR(16) PRIMARY KEY,
    user_name VARCHAR(64)  NOT NULL,
    phone     VARCHAR(32)
);

CREATE TABLE item (
    item_id   VARCHAR(16) PRIMARY KEY,
    item_name VARCHAR(128) NOT NULL,
    category  VARCHAR(64)  NOT NULL,
    price     NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    status    SMALLINT NOT NULL CHECK (status IN (0, 1)),
    seller_id VARCHAR(16) NOT NULL,
    CONSTRAINT fk_item_seller FOREIGN KEY (seller_id) REFERENCES "User" (user_id)
);

CREATE TABLE orders (
    order_id  VARCHAR(16) PRIMARY KEY,
    item_id   VARCHAR(16) NOT NULL,
    buyer_id  VARCHAR(16) NOT NULL,
    order_date DATE NOT NULL,
    CONSTRAINT uq_orders_item UNIQUE (item_id),
    CONSTRAINT fk_orders_item FOREIGN KEY (item_id) REFERENCES item (item_id),
    CONSTRAINT fk_orders_buyer FOREIGN KEY (buyer_id) REFERENCES "User" (user_id)
);

-- 已售商品视图：商品名 + 买家 ID（与作业表述一致的两列）
CREATE VIEW sold_items_view AS
SELECT
    i.item_name AS item_name,
    o.buyer_id  AS buyer_id
FROM orders AS o
JOIN item AS i ON i.item_id = o.item_id;

-- 未售商品视图：未售出商品的常用列
CREATE VIEW unsold_items_view AS
SELECT
    item_id,
    item_name,
    category,
    price,
    seller_id
FROM item
WHERE status = 0;

-- 种子顺序：User → Item → Orders
INSERT INTO "User" (user_id, user_name, phone) VALUES
    ('u001', '张三', '13800001001'),
    ('u002', '李四', '13800001002'),
    ('u003', '王五', '13800001003'),
    ('u004', '赵六', '13800001004');

INSERT INTO item (item_id, item_name, category, price, status, seller_id) VALUES
    ('i001', '高等数学（第七版）', 'Books', 28.00, 0, 'u001'),
    ('i002', 'LED 台灯', 'DailyGoods', 35.00, 1, 'u001'),
    ('i003', '机械键盘 87 键', 'Electronics', 299.00, 0, 'u002'),
    ('i004', '抽纸整箱', 'DailyGoods', 32.50, 1, 'u004'),
    ('i005', '羽毛球拍', 'Sports', 45.00, 0, 'u003');

INSERT INTO orders (order_id, item_id, buyer_id, order_date) VALUES
    ('o001', 'i002', 'u003', DATE '2026-03-15'),
    ('o002', 'i004', 'u002', DATE '2026-04-02');

COMMIT;
